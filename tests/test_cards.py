import time
from datetime import datetime, timezone

import httpx

from osugacha_ev.api import OsuGachaClient
from osugacha_ev.app import App
from osugacha_ev.config import Settings


def iso(ts):
    return datetime.fromtimestamp(ts, timezone.utc).isoformat()


def make_app(tmp_path, rows_by_rarity, calls):
    drops = tmp_path / "d.yaml"
    drops.write_text("items:\n  fuel: fuel\nmaps: []\n", encoding="utf-8")
    settings = Settings("t", 1, "og_test", drops, tmp_path / "db.sqlite")

    def handler(request):
        calls.append(request)
        assert request.url.params["kind"] == "card"
        return httpx.Response(200, json={"items": rows_by_rarity[request.url.params["rarity"]]})

    return App(settings, client=OsuGachaClient("og_test", transport=httpx.MockTransport(handler)))


def row(lid, price, rarity, created, mode="bin", level=1):
    return {
        "id": lid, "price": price, "mode": mode, "createdAt": iso(created), "kind": "card",
        "card": {"rarity": rarity, "level": level, "mods": [], "serialNo": 7, "sig": None},
    }


async def test_card_alert_fires_for_a_fresh_undercut_once(tmp_path):
    now = time.time()
    rows = {
        "mythic": [row("a", 3000, "mythic", now - 60), row("b", 3999, "mythic", now - 9000),
                   row("c", 4000, "mythic", now - 9000)],
        "divine": [row("d", 59996, "divine", now - 9000), row("e", 60000, "divine", now - 9000)],
    }
    calls = []
    app = make_app(tmp_path, rows, calls)
    assert await app.card_alerts(now) == [] and not calls  # no subscribers, no api calls
    app.store.set_card_alert(5, 15)
    pings = await app.card_alerts(now)
    assert len(pings) == 1 and pings[0][0] == 5
    title, text = pings[0][1].title, pings[0][1].description
    assert title == "mythic card undercut" and "3,000" in text and "3,999" in text and "25.0%" in text
    assert text == text.lower()
    assert await app.card_alerts(now) == []  # each listing pings once
    await app.aclose()


async def test_card_alert_ignores_auctions_old_listings_and_small_gaps(tmp_path):
    now = time.time()
    rows = {
        "mythic": [row("a", 100, "mythic", now - 60, mode="auction"), row("b", 3900, "mythic", now - 60),
                   row("c", 3999, "mythic", now - 60)],  # 2.5% under: not an undercut
        "divine": [row("d", 40000, "divine", now - 99999), row("e", 60000, "divine", now - 99999)],  # old
    }
    app = make_app(tmp_path, rows, [])
    app.store.set_card_alert(5, 15)
    assert await app.card_alerts(now) == []
    app.store.set_card_alert(5, None)
    assert app.store.card_subscribers() == []
    await app.aclose()
