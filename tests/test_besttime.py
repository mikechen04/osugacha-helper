import httpx
import pytest

from osugacha_ev import fmt
from osugacha_ev.api import OsuGachaClient
from osugacha_ev.app import App
from osugacha_ev.config import Settings
from osugacha_ev.store import SnapshotStore

T0 = 1_000_000.0


def test_vanished_listing_counts_as_gone_once():
    store = SnapshotStore(":memory:")
    assert store.observe("fuel", [("a", 7000.0, 2), ("b", 7500.0, 1)], T0, True) == 0
    assert store.observe("fuel", [("b", 7500.0, 1), ("c", 7600.0, 1)], T0 + 900, True) == 1
    assert store.observe("fuel", [("b", 7500.0, 1), ("c", 7600.0, 1)], T0 + 1800, True) == 0
    qty = store._db.execute("select sum(qty) from gone where item = 'fuel'").fetchone()[0]
    assert qty == 2


def test_gap_between_looks_is_not_trusted():
    store = SnapshotStore(":memory:")
    store.observe("fuel", [("a", 7000.0, 1)], T0, True)
    # the bot was off for hours: whatever vanished may have gone any time
    assert store.observe("fuel", [], T0 + 6 * 3600, True) == 0
    assert store._db.execute("select count(*) from open_listings").fetchone()[0] == 0


def test_incomplete_book_never_counts_anything_gone():
    store = SnapshotStore(":memory:")
    store.observe("fuel", [("a", 7000.0, 1)], T0, True)
    assert store.observe("fuel", [], T0 + 900, False) == 0
    assert store.observe("fuel", [("a", 7000.0, 1)], T0 + 1800, True) == 0  # a was still open


def fill(store, days, hour_bump):
    """a snapshot every 15 min; lbin 7000 plus a bump at the given utc hours."""
    start = 86400 * 100  # midnight utc
    for step in range(days * 96):
        ts = start + step * 900
        hour = (ts // 3600) % 24
        store.add({"fuel": 7000.0 + hour_bump.get(hour, 0)}, ts)
    return start + days * 86400


def test_hour_profile_finds_the_expensive_and_cheap_hours():
    store = SnapshotStore(":memory:")
    now = fill(store, 4, {18: 400, 19: 300, 4: -400})
    profile = store.hour_profile("fuel", now)
    assert profile.span >= 3 * 86400
    best = max(profile.hours, key=lambda h: profile.hours[h][0])
    worst = min(profile.hours, key=lambda h: profile.hours[h][0])
    assert (best, worst) == (18, 4)
    assert all(n >= 4 for _, n in profile.hours.values())


@pytest.fixture
def app(tmp_path):
    drops = tmp_path / "d.yaml"
    drops.write_text("items:\n  fuel: fuel\nmaps: []\n", encoding="utf-8")
    settings = Settings("t", 1, "og_test", drops, tmp_path / "db.sqlite")
    client = OsuGachaClient("og_test", transport=httpx.MockTransport(lambda r: httpx.Response(200, json={})))
    return App(settings, client=client)


async def test_besttime_report_waits_for_a_day_of_data(app):
    app.store.add({"fuel": 7000.0}, T0)
    app.store.add({"fuel": 7000.0}, T0 + 3600)
    report = await app.besttime_report("fuel", T0 + 3600)
    assert "need 24h" in report.description and "have 1h" in report.description
    assert report.description == report.description.lower()


async def test_besttime_report_lists_sell_and_buy_hours(app):
    now = fill(app.store, 4, {18: 400, 19: 300, 4: -400, 5: -300})
    for k in range(5):  # listings vanishing at 19:00 utc
        ts = now - 86400 + 19 * 3600 + k * 60
        app.store.observe("fuel", [(f"x{k}", 7000.0, 3)], ts - 30, True, max_gap=10_000)
        app.store.observe("fuel", [], ts, True, max_gap=10_000)
    report = await app.besttime_report("fuel", now)
    lines = report.description.strip("`\n").splitlines()
    assert lines[0].startswith("fuel ♥ 3d ") and lines[0].endswith("utc")
    sell = lines[lines.index("sell high") + 1]
    assert sell.startswith("18:00") and "+" in sell
    buy = lines[lines.index("buy low") + 1]
    assert buy.startswith("04:00") and "-" in buy
    assert any(l.startswith("busiest:") and "19:00" in l for l in lines)
    assert report.description == report.description.lower()
    assert max(len(l) for l in lines) <= 54
