import httpx
import pytest

from osugacha_ev import fmt
from osugacha_ev.alerts import detect
from osugacha_ev.api import Listing, OsuGachaClient
from osugacha_ev.app import App
from osugacha_ev.config import Settings
from osugacha_ev.store import SnapshotStore

NOW = 1_000_000.0


def lst(id, unit, qty=1, age=60):
    return Listing(id, unit, qty, round(unit * qty), NOW - age)


def test_fresh_listing_ten_percent_under_next_alerts():
    alerts = detect([lst("a", 6600), lst("b", 7400), lst("c", 7500)], 10, NOW)
    assert [a.listing.id for a in alerts] == ["a"]
    assert alerts[0].next_lbin == 7400
    assert alerts[0].below_pct == pytest.approx((1 - 6600 / 7400) * 100)


def test_exactly_ten_percent_counts_and_just_under_does_not():
    assert detect([lst("a", 6660), lst("b", 7400)], 10, NOW)
    assert not detect([lst("a", 6700), lst("b", 7400)], 10, NOW)


def test_old_listing_does_not_alert():
    assert not detect([lst("a", 6000, age=3600), lst("b", 7400)], 10, NOW)


def test_two_cheap_listings_both_alert_against_the_rest():
    alerts = detect([lst("a", 6000), lst("b", 6100), lst("c", 7500)], 10, NOW)
    assert [a.listing.id for a in alerts] == ["a", "b"]
    assert all(a.next_lbin == 7500 for a in alerts)


def test_normal_market_and_single_listing_do_not_alert():
    assert not detect([lst("a", 7499), lst("b", 7499), lst("c", 8000)], 10, NOW)
    assert not detect([lst("a", 1000)], 10, NOW)
    assert not detect([], 10, NOW)


def test_gap_far_up_the_book_is_not_a_quicksell():
    book = [lst(str(i), 7000 + i) for i in range(4)] + [lst("far", 9000)]
    assert not detect(book, 10, NOW)


def test_threshold_is_per_user():
    book = [lst("a", 6900), lst("b", 7400)]
    assert not detect(book, 10, NOW)
    assert detect(book, 5, NOW)


def test_alert_text_style():
    alert = detect([lst("a", 6000, qty=2, age=130), lst("b", 7400)], 10, NOW)[0]
    title, body, footer = fmt.alert_text(alert)
    for text in (title, body, footer):
        assert text == text.lower()
        assert "—" not in text
    lines = body.strip("`\n").splitlines()
    assert lines[0] == "lbin   ★6,000 x2"
    assert lines[1] == "total  ★12,000"
    assert lines[2] == "next   ★7,400"
    assert lines[3].startswith("below  18.9%") and "2m ago" in lines[3]
    assert len(footer.splitlines()) == 1


def test_subscriptions_and_dedupe():
    store = SnapshotStore(":memory:")
    assert store.subscribers() == [] and store.get_alert(1) is None
    store.set_alert(1, 10.0)
    store.set_alert(1, 15.0)
    store.set_alert(2, 10.0)
    assert sorted(store.subscribers()) == [(1, 15.0), (2, 10.0)]
    store.set_alert(2, None)
    assert store.subscribers() == [(1, 15.0)]
    assert store.mark_alerted("x", 1, NOW) is True
    assert store.mark_alerted("x", 1, NOW) is False
    assert store.mark_alerted("x", 2, NOW) is True
    store.prune_alerted(NOW + 1)
    assert store.mark_alerted("x", 1, NOW) is True


def make_app(tmp_path, rows, calls):
    drops = tmp_path / "d.yaml"
    drops.write_text("maps: []\n", encoding="utf-8")
    settings = Settings("t", 1, "og_test", drops, tmp_path / "db.sqlite")

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json={"items": rows, "total": len(rows)})

    return App(settings, client=OsuGachaClient("og_test", transport=httpx.MockTransport(handler)))


def row(id, price, qty, created):
    return {"id": id, "kind": "item", "price": price, "mode": "bin", "createdAt": created,
            "item": {"id": "fuel", "qty": qty}}


async def test_fuel_alerts_pings_once_per_listing_and_skips_without_subscribers(tmp_path):
    from datetime import datetime, timezone

    now = datetime(2026, 11, 3, 5, 0, tzinfo=timezone.utc).timestamp()
    rows = [
        row("quick", 6000, 1, "2026-11-03T04:58:00.000Z"),
        row("a", 7400, 1, "2026-11-03T01:00:00.000Z"),
        row("b", 7500, 1, "2026-11-03T01:00:00.000Z"),
    ]
    calls = []
    app = make_app(tmp_path, rows, calls)

    assert await app.fuel_alerts(now) == []
    assert calls == []  # no subscribers, no api call

    app.store.set_alert(7, 10.0)
    pings = await app.fuel_alerts(now)
    assert [uid for uid, _ in pings] == [7]
    assert pings[0][1].title == "fuel quicksell"
    assert await app.fuel_alerts(now + 30) == []  # same listing, already told
    await app.aclose()
