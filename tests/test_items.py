import httpx

from osugacha_ev import fmt
from osugacha_ev.api import OsuGachaClient
from osugacha_ev.app import App
from osugacha_ev.config import Settings
from osugacha_ev.items import item_name, sort_items


def test_names_cover_every_item_kind():
    assert item_name("replay_2") == "silver replay"
    assert item_name("boss_trophy") == "boss trophy"
    assert item_name("platinum_trophy") == "platinum trophy"
    assert item_name("insignia_cc_4") == "mage insig 4"
    assert item_name("insignia_support_1") == "supp insig 1"
    assert item_name("mod_fragment") == "mod fragment"
    assert item_name("brand_new_thing") == "brand new thing"


def test_sort_puts_fuel_replays_fragments_trophies_then_insignia():
    ids = ["insignia_cc_1", "emerald_trophy", "insignia_tank_4", "weird", "replay_3", "replay_1",
           "boss_trophy", "mod_fragment", "fuel", "insignia_tank_2", "insignia_dps_1", "insignia_tank_2"]
    assert sort_items(ids) == [
        "fuel", "replay_1", "replay_3", "mod_fragment", "boss_trophy", "emerald_trophy",
        "insignia_tank_2", "insignia_tank_4", "insignia_dps_1", "insignia_cc_1", "weird",
    ]


def make_app(tmp_path, calls):
    drops = tmp_path / "d.yaml"
    drops.write_text("items:\n  fuel: fuel\n  replay_1: bronze replay\nmaps: []\n", encoding="utf-8")
    settings = Settings("t", 1, "og_test", drops, tmp_path / "db.sqlite")

    def handler(request):
        calls.append(request)
        rows = [
            {"mode": "bin", "item": {"id": "platinum_trophy", "qty": 1}},
            {"mode": "bin", "item": {"id": "insignia_tank_4", "qty": 2}},
            {"mode": "auction", "item": {"id": "secret_auction_only", "qty": 1}},
            {"mode": "bin", "item": {"id": "fuel", "qty": 1}},
        ]
        return httpx.Response(200, json={"items": rows, "total": len(rows)})

    return App(settings, client=OsuGachaClient("og_test", transport=httpx.MockTransport(handler)))


async def test_market_scan_finds_new_items_and_caches(tmp_path):
    calls = []
    app = make_app(tmp_path, calls)
    ids = await app.market_item_ids()
    assert ids == ["fuel", "replay_1", "platinum_trophy", "insignia_tank_4"]  # drops.yaml names are kept
    assert "secret_auction_only" not in ids
    assert calls[0].url.params["kind"] == "item"
    await app.market_item_ids()
    assert len(calls) == 1  # cached for the next 15 minutes
    await app.aclose()


def test_prices_table_stays_inside_an_embed_however_many_items():
    rows = [(f"item {i}", 100.0, None, False, 3) for i in range(200)]
    table = fmt.prices_table(rows, 1_762_144_320)
    assert len(table) < 4000
    assert "+140 more items" in table
