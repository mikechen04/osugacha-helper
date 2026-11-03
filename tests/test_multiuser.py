import httpx
import pytest

from osugacha_ev.api import OsuGachaClient
from osugacha_ev.app import App
from osugacha_ev.config import Settings
from osugacha_ev.store import SnapshotStore

PRIVATE = ("wallet", "items", "team", "account", "cards", "mods?", "depths")


def test_links_are_per_discord_user():
    store = SnapshotStore(":memory:")
    assert store.get_link(1) is None
    store.set_link(1, "Camo")
    store.set_link(2, "Vaxei")
    store.set_link(1, "Camo2")
    assert (store.get_link(1), store.get_link(2)) == ("Camo2", "Vaxei")
    store.set_link(1, None)
    assert store.get_link(1) is None and store.get_link(2) == "Vaxei"


def card(name, pid, cls="tank", **kw):
    base = {
        "id": f"id-{name}", "rarity": "common", "level": 20, "ascension": 0, "eidolon": 0, "xp": 0,
        "passive": None, "sig": None, "mods": [],
        "player": {"id": pid, "username": name, "cls": cls, "passive": None},
    }
    return {**base, **kw}


def listing_page(item_id):
    price = {"replay_1": 150, "replay_2": 600, "replay_3": 3000, "insignia_tank_1": 40, "insignia_tank_2": 50}.get(item_id, 10)
    return {"items": [{"id": f"{item_id}-{i}", "kind": "item", "mode": "bin", "price": price * (i + 1),
                       "item": {"id": item_id, "qty": i + 1}} for i in range(3)], "total": 3}


def make_app(tmp_path, seen):
    drops = tmp_path / "d.yaml"
    drops.write_text("maps: []\n", encoding="utf-8")
    settings = Settings("t", 1, "og_test", drops, tmp_path / "db.sqlite")

    def handler(request):
        path = request.url.path.removeprefix("/api/")
        seen.append(path)
        if path == "users/Some Player/profile":
            return httpx.Response(200, json={
                "user": {"username": "Some Player"},
                "stats": {"level": {"level": 26}, "team": {"power": 12345}},
                "squad": [card("Tanky", 7)],
            })
        if path == "users/Some Player/mods":
            return httpx.Response(200, json={"items": [], "total": 0})
        if path == "market/listings":
            params = request.url.params
            if params.get("kind") == "card":
                return httpx.Response(200, json={"items": [
                    {"kind": "card", "mode": "bin", "price": 5, "card": {"player": {"id": 99}}},
                    {"kind": "card", "mode": "bin", "price": 150, "card": {"player": {"id": 7}, "sig": None}},
                    {"kind": "card", "mode": "bin", "price": 45000,
                     "card": {"player": {"id": 7}, "sig": {"id": "volley", "tier": "ssr"}}},
                ], "total": 3})
            return httpx.Response(200, json=listing_page(params.get("itemId", "x")))
        if path.startswith("users/Nobody"):
            return httpx.Response(404, json={"error": {"code": "not_found"}})
        return httpx.Response(500, json={"error": "unexpected " + path})

    return App(settings, client=OsuGachaClient("og_test", transport=httpx.MockTransport(handler)))


async def test_bp_uses_public_data_only(tmp_path):
    seen = []
    app = make_app(tmp_path, seen)
    report = await app.bp_report("Some Player")
    assert "team power 12,345" in report.description and "account lv 26" in report.description
    assert report.title == "best bp upgrades for some player"
    # the key owner's wallet, items, team and cards must never be read for a lookup
    for path in seen:
        assert path.startswith(("users/Some Player", "market/listings")), path
    assert "wallet" not in report.description
    # a spare copy of this player costs the cheapest listing of that player, not another's
    assert "feed copy e0 to e1" in report.description and "★150" in report.description
    await app.aclose()


async def test_bp_unknown_player_and_find_user(tmp_path):
    seen = []
    app = make_app(tmp_path, seen)
    report = await app.bp_report("Nobody")
    assert report.description == "no player named nobody"
    assert await app.find_user("Nobody") is None
    await app.aclose()


async def test_signature_card_is_priced_with_signature_copies(tmp_path):
    app = make_app(tmp_path, [])
    normal = card("Tanky", 7)
    signed = card("Tanky", 7, sig={"id": "volley", "tier": "ssr"})
    other_sig = card("Tanky", 7, sig={"id": "bite", "tier": "r"})
    assert await app._copy_price(normal) == 150
    assert await app._copy_price(signed) == 45000
    assert await app._copy_price(other_sig) is None  # nobody lists that signature
    await app.aclose()
