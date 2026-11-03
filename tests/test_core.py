import re

import httpx
import pytest

from osugacha_ev import fmt
from osugacha_ev.api import ApiError, OsuGachaClient
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


def test_repo_drops_yaml_is_valid():
    from osugacha_ev.config import ROOT

    assert load_drops(ROOT / "drops.yaml").entries


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
        async def lbin(self, item_id):
            calls.append(item_id)
            return 7300.0

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
    await service.get(["fuel"], force=True)
    assert len(calls) == 3


# snapshots


def test_change_vs_12h_when_available():
    store = SnapshotStore(":memory:")
    now = 1_000_000.0
    store.add({"fuel": 7000.0}, now - 12 * 3600 - 10)
    store.add({"fuel": 7100.0}, now - 3600)
    change = store.change("fuel", 7350.0, now)
    assert change.pct == pytest.approx(5.0)
    assert change.label == "12h"


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
            DiffDrops("everything will freeze", "expert+", 300, 400),
        ],
        LBINS,
        7300,
    )
    table = fmt.ev_table(rows)
    footer = fmt.ev_footer(7300, 1_762_144_320)
    for text in (table, footer):
        assert text == text.lower()
        assert "—" not in text
    body = table.strip("`\n").splitlines()
    assert max(len(line) for line in body) <= 38
    assert body[0].split() == ["#", "map", "diff", "gross", "ev", "profit"]
    assert "gal collapse*" not in table  # 12 chars + * would overflow the column
    assert "gal collaps*" in table
    assert "* estimated drops" in table
    assert "\n" not in footer and footer == "fuel lbin 7,300 | 11/03 04:32 utc"


def test_prices_output_style():
    store = SnapshotStore(":memory:")
    store.add({"fuel": 7000.0}, 1_000_000 - 3 * 3600)
    change = store.change("fuel", 7350.0, 1_000_000)
    table = fmt.prices_table(
        [("fuel", 7350.0, change), ("gold replay", None, None), ("mod fragment", 12.0, None)]
    )
    assert table == table.lower()
    lines = table.strip("`\n").splitlines()
    assert "vs 3h" in lines[0]
    assert "+5.0%" in lines[1] and "7,350" in lines[1]
    assert "n/a" in lines[2]
    assert max(len(line) for line in lines) <= 32


def test_lc_strips_em_dashes_and_caps():
    assert fmt.lc("Hello — World") == "hello - world"
    assert not re.search(r"[A-Z]", fmt.lc("ABC"))
