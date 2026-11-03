import re

import httpx
import pytest

from osugacha_ev import fmt
from osugacha_ev.api import ApiError, Fetch, Listing, OsuGachaClient
from osugacha_ev.drops import DiffDrops, ItemDrop, load_drops
from osugacha_ev.ev import compute, rank
from osugacha_ev.prices import PriceService
from osugacha_ev.store import SnapshotStore

GC = DiffDrops(
    map="galaxy collapse",
    diff="tbd",
    stars_low=440,
    stars_high=520,
    items=(ItemDrop("replay_1", 1, 3), ItemDrop("replay_2", 1, 1)),
)
LBINS = {"replay_1": 1000.0, "replay_2": 5000.0}


def test_ev_math_matches_spec():
    row = compute(GC, LBINS, fuel_lbin=7200)
    per_run_items = 2 * 1000 + 1 * 5000
    assert row.gross == (480 + per_run_items) * 6
    assert row.after_fee == 480 * 6 + per_run_items * 6 * 0.98
    assert row.profit == pytest.approx(row.after_fee - 7200)


def test_fee_never_touches_stars():
    stars_only = DiffDrops("m", "d", 500, 500)
    assert compute(stars_only, {}, 0).after_fee == 3000


def test_missing_item_counts_as_zero_and_is_reported():
    row = compute(GC, {"replay_1": 1000.0}, 0)
    assert row.missing == ("replay_2",)
    assert row.gross == (480 + 2000) * 6


def test_rank_sorts_by_profit():
    poor = DiffDrops("poor", "d", 100, 100)
    rows = rank([poor, GC], LBINS, 7200)
    assert [r.map for r in rows] == ["galaxy collapse", "poor"]


def test_drops_yaml_loads_and_lowercases(tmp_path):
    path = tmp_path / "d.yaml"
    path.write_text(
        "items:\n  fuel: Fuel\nmaps:\n  - map: Galaxy Collapse\n    diff: EX\n"
        "    estimated: true\n    stars: [440, 520]\n    items:\n      replay_1: [1, 3]\n"
        "      replay_2: 1\n",
        encoding="utf-8",
    )
    table = load_drops(path)
    entry = table.entries[0]
    assert entry.map == "galaxy collapse" and entry.diff == "ex" and entry.estimated
    assert entry.stars_avg == 480
    assert [d.avg for d in entry.items] == [2, 1]
    assert table.names == {"fuel": "fuel"}
    assert table.item_ids == ["fuel", "replay_1", "replay_2"]


def test_measured_average_overrides_range_midpoint(tmp_path):
    path = tmp_path / "d.yaml"
    path.write_text(
        "maps:\n  - map: gc\n    diff: gal\n    stars: [440, 520]\n    items:\n"
        "      replay_1: {range: [1, 3], avg: 236/120}\n"
        "      replay_2: {range: [0, 1], avg: 77/120}\n",
        encoding="utf-8",
    )
    bronze, silver = load_drops(path).entries[0].items
    assert bronze.avg == pytest.approx(236 / 120)
    assert silver.avg == pytest.approx(77 / 120)
    assert (silver.low, silver.high) == (0, 1)
    row = compute(load_drops(path).entries[0], {"replay_1": 150.0, "replay_2": 600.0}, 7500)
    assert row.gross == pytest.approx((480 + 236 / 120 * 150 + 77 / 120 * 600) * 6)


def test_mods_block_expands_to_priced_ids(tmp_path):
    path = tmp_path / "d.yaml"
    path.write_text(
        "maps:\n  - map: rc\n    diff: top\n    stars: 0\n"
        "    mods: {count: 2, types: [ht, sd, dt], rarity: {4: 0.9, 5: 0.1}}\n",
        encoding="utf-8",
    )
    entry = load_drops(path).entries[0]
    assert [d.item for d in entry.items] == [
        "mod:ht:4", "mod:ht:5", "mod:sd:4", "mod:sd:5", "mod:dt:4", "mod:dt:5"
    ]
    assert sum(d.avg for d in entry.items) == pytest.approx(2)
    assert sum(d.avg for d in entry.items if d.item.endswith(":5")) == pytest.approx(0.2)
    lbins = {f"mod:{t}:{r}": p for t in ("ht", "sd", "dt") for r, p in ((4, 1000.0), (5, 5000.0))}
    row = compute(entry, lbins, 0)
    assert row.gross == pytest.approx(2 * (0.9 * 1000 + 0.1 * 5000) * 6)


def test_mods_block_rejects_bad_weights(tmp_path):
    path = tmp_path / "d.yaml"
    path.write_text(
        "maps:\n  - map: rc\n    diff: top\n    mods: {count: 2, types: [ht], rarity: {4: 0.5}}\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError):
        load_drops(path)


async def test_mod_lbin_filters_type_and_rarity():
    seen = []

    def handler(req):
        seen.append(req.url.params)
        rows = [
            {"price": 900, "mode": "bin", "mod": {"type": "ht", "rarity": 4}},
            {"price": 100, "mode": "bin", "mod": {"type": "sd", "rarity": 4}},
            {"price": 50, "mode": "auction", "mod": {"type": "ht", "rarity": 4}},
            {"price": 700, "mode": "bin", "mod": {"type": "ht", "rarity": 4}},
        ]
        return httpx.Response(200, json={"items": rows, "total": 4})

    client = client_for(handler)
    assert await client.lbin("mod:ht:4") == 700
    assert seen[0]["kind"] == "mod" and seen[0]["modType"] == "ht" and seen[0]["modRarity"] == "4"
    await client.aclose()


def test_repo_drops_yaml_is_valid():
    from osugacha_ev.config import ROOT

    table = load_drops(ROOT / "drops.yaml")
    assert len(table.entries) >= 7
    for entry in table.entries:
        assert len(entry.label) <= 15 and len(entry.diff) <= 5
        assert all(d.item in table.names or d.item.startswith("mod:") for d in entry.items)


# api


def listing(price, qty, item="fuel", mode="bin"):
    return {"kind": "item", "price": price, "mode": mode, "item": {"id": item, "qty": qty}}


def client_for(handler, sleeps=None):
    async def sleep(seconds):
        if sleeps is not None:
            sleeps.append(seconds)

    return OsuGachaClient("og_test", transport=httpx.MockTransport(handler), sleep=sleep)


async def test_lbin_is_lowest_per_unit_and_ignores_auctions():
    page = {
        "items": [
            listing(8000, 1),
            listing(14600, 2),
            listing(329956, 44),
            listing(1, 1, mode="auction"),
        ],
        "total": 4,
    }
    client = client_for(lambda req: httpx.Response(200, json=page))
    assert await client.lbin("fuel") == 7300
    await client.aclose()


async def test_lbin_paginates_and_sends_bearer():
    seen = []

    def handler(req):
        seen.append(req)
        offset = int(req.url.params["offset"])
        if offset == 0:
            return httpx.Response(200, json={"items": [listing(9000, 1)] * 100, "total": 101})
        return httpx.Response(200, json={"items": [listing(7000, 1)], "total": 101})

    client = client_for(handler)
    assert await client.lbin("fuel") == 7000
    assert len(seen) == 2
    assert seen[0].headers["authorization"] == "Bearer og_test"
    assert seen[0].url.params["itemId"] == "fuel"
    await client.aclose()


async def test_lbin_none_when_unlisted():
    client = client_for(lambda req: httpx.Response(200, json={"items": [], "total": 0}))
    assert await client.lbin("replay_3") is None
    await client.aclose()


async def test_429_waits_retry_after_then_succeeds():
    calls = {"n": 0}
    sleeps = []

    def handler(req):
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(429, headers={"Retry-After": "7"}, json={})
        return httpx.Response(200, json={"items": [listing(100, 1)], "total": 1})

    client = client_for(handler, sleeps)
    assert await client.lbin("fuel") == 100
    assert sleeps == [7.0]
    await client.aclose()


async def test_http_error_raises():
    client = client_for(lambda req: httpx.Response(403, json={"error": {}}))
    with pytest.raises(ApiError):
        await client.lbin("fuel")
    await client.aclose()


async def test_price_cache_ttl():
    calls = []

    class FakeClient:
        async def fetch(self, item_id):
            calls.append(item_id)
            return Fetch([Listing(str(i), 7300.0 + i, 1, 7300, 0) for i in range(5)], True)

    now = [1000.0]
    service = PriceService(FakeClient(), ttl=300, clock=lambda: now[0])
    await service.get(["fuel"])
    now[0] += 299
    await service.get(["fuel"])
    assert calls == ["fuel"]
    now[0] += 2
    book = await service.get(["fuel"])
    assert calls == ["fuel", "fuel"]
    assert book.lbins == {"fuel": 7300.0}
    assert book.quotes["fuel"].listings == 5
    await service.get(["fuel"], force=True)
    assert len(calls) == 3


# snapshots


def test_change_vs_6h_when_available():
    store = SnapshotStore(":memory:")
    now = 1_000_000.0
    store.add({"fuel": 7000.0}, now - 6 * 3600 - 10)
    store.add({"fuel": 7100.0}, now - 3600)
    change = store.change("fuel", 7350.0, now)
    assert change.pct == pytest.approx(5.0)
    assert change.label == "6h"


def test_change_falls_back_to_oldest_snapshot_with_label():
    store = SnapshotStore(":memory:")
    now = 1_000_000.0
    store.add({"fuel": 7000.0}, now - 3 * 3600)
    store.add({"fuel": 7100.0}, now - 1800)
    change = store.change("fuel", 7700.0, now)
    assert change.pct == pytest.approx(10.0)
    assert change.label == "3h"


def test_change_minutes_label_and_no_history():
    store = SnapshotStore(":memory:")
    now = 1_000_000.0
    assert store.change("fuel", 7000.0, now) is None
    store.add({"fuel": 7000.0}, now - 20 * 60)
    assert store.change("fuel", 7000.0, now).label == "20m"
    assert store.change("fuel", None, now) is None


# formatting


def test_ev_output_style():
    rows = rank(
        [
            DiffDrops(
                "galaxy collapse", "gal", 440, 520, GC.items, estimated=True, short="gal collapse"
            ),
            DiffDrops("everything will freeze", "expert+", 300, 400, short="will freeze"),
        ],
        LBINS,
        7300,
    )
    table = fmt.ev_table(rows, 7300, 1_762_144_320)
    for text in (table, fmt.EV_FOOTER, fmt.PRICES_FOOTER):
        assert text == text.lower()
        assert "—" not in text
        assert len(text.splitlines()) == 1 or text is table
    body = table.strip("`\n").splitlines()
    assert body[0] == "fuel ★7,300 (lbin) ♥ 6 runs ♥ prices 04:32 utc"
    assert body[1].split() == ["#", "map", "diff", "gross", "ev", "after", "fuel"]
    assert set(body[2]) == {"-"} and len(body[2]) == len(body[1])
    assert max(len(line) for line in body) <= 54
    assert "gal collapse*" in table
    assert "★44,880" in table
    assert "best: gal collapse gal ♥ ★" in table
    assert "* estimated drops" in table


def test_prices_output_style():
    store = SnapshotStore(":memory:")
    store.add({"fuel": 7000.0}, 1_000_000 - 3 * 3600)
    change = store.change("fuel", 7350.0, 1_000_000)
    table = fmt.prices_table(
        [
            ("fuel", 7350.0, change, False, 26),
            ("gold replay", None, None, False, None),
            ("mod fragment", 12.0, None, True, 125_850),
        ],
        1_762_144_320,
    )
    assert table == table.lower()
    lines = table.strip("`\n").splitlines()
    assert lines[0] == "per unit ♥ prices 04:32 utc"
    assert "vs 3h" in lines[1] and set(lines[2]) == {"-"}
    assert "+5.0%" in lines[3] and "★7,350" in lines[3]
    assert "n/a" in lines[4]
    assert lines[5].endswith(" !")
    assert max(len(line) for line in lines) <= 54


def test_lc_strips_em_dashes_and_caps():
    assert fmt.lc("Hello — World") == "hello - world"
    assert not re.search(r"[A-Z]", fmt.lc("ABC"))


def test_repo_drops_match_hand_calculation_with_fixed_prices():
    """freedom dive and galaxy collapse worked by hand, fuel at 7,500."""
    from osugacha_ev.config import ROOT

    entries = {e.map: e for e in load_drops(ROOT / "drops.yaml").entries}
    lbins = {
        "replay_1": 150.0, "replay_2": 600.0,
        "insignia_support_2": 300.0, "insignia_support_3": 800.0,
        "insignia_cc_2": 200.0, "insignia_cc_3": 250.0,
    }
    # freedom dive: no stars. per run 300 + 1.5 x 800 + 200 + 1.5 x 250 = 2,075
    fd = compute(entries["freedom dive"], lbins, 7500)
    assert fd.gross == pytest.approx(2075 * 6)
    assert fd.after_fee == pytest.approx(2075 * 6 * 0.98)
    assert fd.profit == pytest.approx(2075 * 6 * 0.98 - 7500)
    # galaxy collapse: 480 stars (not fee'd) + 380/199 bronze + 126/199 silver
    gc = compute(entries["galaxy collapse"], lbins, 7500)
    items = 380 / 199 * 150 + 126 / 199 * 600
    assert gc.gross == pytest.approx((480 + items) * 6)
    assert gc.profit == pytest.approx(480 * 6 + items * 6 * 0.98 - 7500)


def test_refill_note_only_when_fuel_lbin_is_above_the_refill():
    rows = rank([DiffDrops("m", "d", 500, 500)], {}, 8000)
    over = fmt.ev_table(rows, 8000, 1_762_144_320)
    assert "note: \u26057,900 refill beats fuel lbin" in over
    assert "refill" not in fmt.ev_table(rows, 7900, 1_762_144_320)
    assert "refill" not in fmt.ev_table(rows, 7500, 1_762_144_320)
    assert over == over.lower() and max(len(l) for l in over.strip("`\n").splitlines()) <= 54
    prices_over = fmt.prices_table([("fuel", 8000.0, None, False, None)], 1_762_144_320)
    prices_ok = fmt.prices_table([("fuel", 7900.0, None, False, None)], 1_762_144_320)
    assert "refill beats fuel lbin" in prices_over and "refill" not in prices_ok
