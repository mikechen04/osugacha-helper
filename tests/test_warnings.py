import httpx
import pytest

from osugacha_ev import fmt
from osugacha_ev.api import OsuGachaClient, Quote
from osugacha_ev.app import App
from osugacha_ev.config import Settings
from osugacha_ev.drops import DiffDrops, ItemDrop
from osugacha_ev.ev import compute, rank
from osugacha_ev.prices import PriceBook, is_thin


def listing(price, qty, item="fuel"):
    return {"kind": "item", "price": price, "mode": "bin", "item": {"id": item, "qty": qty}}


def test_thin_when_few_listings_or_lone_low():
    assert is_thin(Quote(100.0, 2, 0.01))
    assert is_thin(Quote(100.0, 10, 0.5))
    assert not is_thin(Quote(100.0, 10, 0.05))
    assert not is_thin(Quote(100.0, 3, None))
    assert not is_thin(None)


async def test_quote_reports_depth_and_gap():
    page = {"items": [listing(200, 2), listing(150, 1), listing(900, 3)], "total": 3}
    client = OsuGachaClient("og_test", transport=httpx.MockTransport(lambda r: httpx.Response(200, json=page)))
    quote = await client.quote("fuel")
    assert quote.lbin == 100 and quote.listings == 3
    assert quote.gap == pytest.approx(0.5)
    await client.aclose()


async def test_quote_none_when_unlisted():
    client = OsuGachaClient(
        "og_test", transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"items": [], "total": 0}))
    )
    assert await client.quote("fuel") is None
    await client.aclose()


GC = DiffDrops(
    map="m",
    diff="d",
    stars_low=0,
    stars_high=0,
    items=(ItemDrop("big", 1, 1), ItemDrop("small", 1, 1)),
)


def test_row_is_shaky_only_when_a_flagged_item_matters():
    lbins = {"big": 1000.0, "small": 10.0}
    assert compute(GC, lbins, 0, {"big"}).shaky
    assert not compute(GC, lbins, 0, {"small"}).shaky
    assert not compute(GC, lbins, 0, set()).shaky


def test_ev_marks_and_note():
    rows = rank([GC], {"big": 1000.0, "small": 10.0}, 0, {"big"})
    table = fmt.ev_table(rows, 7300, 1_762_144_320, fuel_shaky=True)
    body = table.strip("`\n").splitlines()
    assert body[0].startswith("fuel ★7,300! (lbin)")
    assert " m!" in body[3] or body[3].split()[1] == "m!"
    assert fmt.SHAKY_NOTE in body
    assert table == table.lower()
    assert max(len(line) for line in body) <= 50


def test_marks_never_overflow_the_map_column():
    row = rank([DiffDrops("x", "d", 1, 1, short="abcdefghijkl", estimated=True)], {}, 0, set())[0]
    row = type(row)(**{**row.__dict__, "shaky": True})
    assert fmt.map_cell(row) == "abcdefghij*!"


@pytest.fixture
def app(tmp_path):
    drops = tmp_path / "d.yaml"
    drops.write_text("maps: []\n", encoding="utf-8")
    settings = Settings("t", 1, "og_test", drops, tmp_path / "db.sqlite")
    client = OsuGachaClient("og_test", transport=httpx.MockTransport(lambda r: httpx.Response(200, json={})))
    return App(settings, client=client)


def test_shaky_flags_big_move_vs_6h_and_thin_depth(app):
    now = 1_000_000.0
    app.store.add({"calm": 1000.0, "wild": 1000.0, "thin": 1000.0}, now - 6 * 3600 - 5)
    deep = Quote(0, 10, 0.01)
    book = PriceBook(
        quotes={
            "calm": Quote(1100.0, 10, 0.01),  # +10%
            "wild": Quote(1300.0, 10, 0.01),  # +30%
            "thin": Quote(1000.0, 1, None),  # one listing
        },
        fetched_at=now,
    )
    assert deep  # keeps the helper quote used above from looking unused
    assert app.shaky(book, now) == {"wild", "thin"}
    drop = Quote(700.0, 10, 0.01)  # -30%
    assert app.shaky(PriceBook({"calm": drop}, now), now) == {"calm"}
