import math

import pytest

from osugacha_ev import bp as b
from osugacha_ev import fmt, upgrades as up
from osugacha_ev.bp import Card, Mod


def mod(type_, rarity=5, **stats):
    lines = tuple(stats.items()) or (("atkPct", 0.432),)
    return Mod(type_, rarity, lines)


def tank(**kw):
    return Card(cls="tank", rarity="common", level=1, ascension=0, eidolon=0, **kw)


def test_plain_common_tank_by_hand():
    # level 1, no mods: every multiplier is 1, so the power is the plain score
    atk = 62 * 0.85
    hp = 62 * 22 * 1.35
    df = 62 * 1.6 * 1.45
    spd = 100 * 0.94
    offense = atk * (1 + (0.05 + 0.0) * 0.5)
    tough = math.sqrt(hp * (9 / 22) * (1 + df * (0.6 / 1.6) / (200 + 10 * 1)))
    expected = round(offense * tough * (spd / 100) * 1.14 / 9)
    assert b.battle_power(tank()) == expected


def test_eidolon_multiplier_is_five_percent_each_for_a_tank():
    base = b.battle_power(tank())
    assert b.battle_power(tank().with_(eidolon=2)) == pytest.approx(base * 1.10, abs=1)
    assert b.battle_power(tank().with_(eidolon=6)) == pytest.approx(base * 1.30, abs=1)


def test_level_and_ascension_raise_bp():
    c = tank()
    assert b.battle_power(c.with_(level=40)) > b.battle_power(c.with_(level=20)) > b.battle_power(c)
    assert b.battle_power(c.with_(level=20, ascension=1)) > b.battle_power(c.with_(level=20))
    assert b.battle_power(Card("dps", "divine", 80, 6, 0)) > b.battle_power(Card("dps", "common", 80, 6, 0))


def test_level_curve_and_caps():
    assert [b.level_cap(a) for a in range(8)] == [20, 30, 40, 50, 60, 70, 80, 85]
    assert b.level_cap(99) == 170
    assert b.xp_to_next(1) == round(200 + 60 + 1 / 380)
    assert b.xp_to_next(80) == round(200 + 60 * 80 + 80**4 / 380) * 5
    assert b.xp_to_next(110) == round(200 + 60 * 110 + 110**4 / 380) * 10
    assert b.xp_to_next(170) == 0
    assert b.xp_between(1, 4) == sum(b.xp_to_next(i) for i in (1, 2, 3))


def test_stat_multiplier_matches_the_formula():
    assert b.stat_mult(1, 0) == 1
    assert b.stat_mult(11, 0) == pytest.approx(6 ** (10 / 79))
    assert b.stat_mult(41, 3) == pytest.approx(6 ** (40 / 79) * 1.1)
    assert b.stat_mult(80, 7) == pytest.approx(b.stat_mult(80, 6))
    assert b.stat_mult(110, 7) == pytest.approx(b.stat_mult(80, 6) * (1 + 0.5 + 0.4 * 0 + 0.0))


def test_combo_lookup_prefers_a_triple():
    assert b.combos_for(["hd", "dt", "hr"]) == ["hypercarry"]
    assert b.combos_for(["hd", "dt", "nc"]) == ["burst", "kiai"]
    assert b.combos_for(["ez"]) == []


def test_mod_type_bonuses_follow_rarity():
    five = tank(mods=(mod("hr", 5, atk=0.0),))
    three = tank(mods=(mod("hr", 3, atk=0.0),))
    bag5 = b.mod_bag(five)[0]
    bag3 = b.mod_bag(three)[0]
    assert bag5["critRate"] == pytest.approx(0.06)
    assert bag3["critRate"] == pytest.approx(0.042)
    assert b.battle_power(five.with_(level=50)) > b.battle_power(three.with_(level=50))


def test_dps_eidolon_bonuses_only_apply_to_dps():
    bag, *_ = b.mod_bag(Card("dps", "common", 1, 0, 4))
    assert bag["critRate"] == pytest.approx(0.1) and bag["critDmg"] == pytest.approx(0.15)
    assert "critRate" not in b.mod_bag(Card("tank", "common", 1, 0, 4))[0]


def test_from_api_reads_site_shape():
    raw = {
        "rarity": "mythic", "level": 60, "ascension": 4, "eidolon": 1, "passive": None, "sig": None,
        "player": {"cls": "support", "passive": "thrifty"},
        "mods": [{"type": "ht", "rarity": 5, "main": {"stat": "hpPct", "value": 0.432},
                  "subs": [{"stat": "atk", "rolls": 1, "value": 6}]}],
    }
    card = Card.from_api(raw)
    assert card.cls == "support" and card.passive == "thrifty" and not card.sig
    assert card.mods == (Mod("ht", 5, (("hpPct", 0.432), ("atk", 6.0))),)
    sig = Card.from_api({**raw, "sig": {"id": "volley", "tier": "ssr"}})
    assert sig.sig and sig.passive is None


# upgrade costs


def test_ascension_costs_match_the_table():
    assert up.ascension_cost("tank", 1) == ({"insignia_tank_1": 5}, 50)
    assert up.ascension_cost("cc", 3) == ({"insignia_cc_2": 8, "boss_trophy": 2}, 200)
    assert up.ascension_cost("dps", 6) == ({"insignia_dps_3": 30, "boss_trophy": 12}, 10000)
    assert up.ascension_cost("support", 7) == ({"insignia_support_4": 2, "platinum_trophy": 3}, 100000)
    assert up.ascension_cost("support", 8) == (
        {"insignia_support_4": 2, "platinum_trophy": 4}, round(6e5 * 0.75))
    assert up.ascension_gate(4) == 1 and up.ascension_gate(5) == 10
    assert up.ascension_gate(7) == 40 and up.ascension_gate(13) == 60


def test_feeding_costs_half_a_percent_below_80_and_two_above():
    assert up.feed_stars(1, 0, 10_000) == 50
    assert up.feed_stars(80, 0, 10_000) == 200
    need = b.xp_between(78, 80)
    assert up.feed_stars(78, 0, need + 1000) == math.ceil(need * 0.005 + 1000 * 0.02 - 1e-9)


def test_replay_rate_uses_the_cheapest_tier():
    prices = {"replay_1": 150.0, "replay_2": 600.0, "replay_3": 2800.0}
    assert up.replay_rate(prices) == pytest.approx(600 / 7500)
    assert up.replay_rate({}) is None


PRICES = {"replay_1": 150.0, "replay_2": 600.0, "replay_3": 3000.0,
          "insignia_tank_1": 40.0, "insignia_tank_2": 50.0, "insignia_tank_3": 100.0,
          "boss_trophy": 500.0}


def test_level_option_costs_and_ready_flag():
    card = tank().with_(level=10, ascension=0)
    need = b.xp_between(10, 20)
    opt = up.level_option("a", card, 0, 20, PRICES, {}, 1000)
    assert opt.gain > 0 and opt.label == "level 10 to 20" and not opt.ready
    assert opt.stars == pytest.approx(need * (600 / 7500) + up.feed_stars(10, 0, need))
    rich = {"replay_3": math.ceil(need / 30000) + 1}
    assert up.level_option("a", card, 0, 20, PRICES, rich, 1000).ready
    assert up.level_option("a", card, 0, 10, PRICES, {}, 0) is None


def test_ascend_needs_the_level_cap_and_account_level():
    at_cap = tank().with_(level=20, ascension=0)
    assert up.ascend_option("a", at_cap, 0, PRICES, {}, 10, 1, False).stars == 5 * 40 + 50
    assert up.ascend_option("a", at_cap.with_(level=19), 0, PRICES, {}, 10, 1, False) is None
    gated = tank().with_(level=60, ascension=4)
    assert up.ascend_option("a", gated, 0, PRICES, {}, 10, 9, False) is None  # a5 needs level 10
    inv = {"insignia_tank_1": 5}
    assert up.ascend_option("a", at_cap, 0, PRICES, inv, 100, 1, False).ready
    assert not up.ascend_option("a", at_cap, 0, PRICES, inv, 10, 1, False).ready  # 50 stars needed
    both = up.ascend_option("a", at_cap, 0, PRICES, {}, 10, 1, True)
    assert both.label == "a1 + level 30" and both.stars > up.ascension_cost("tank", 1)[1]


def test_missing_prices_drop_the_option():
    at_cap = tank().with_(level=20, ascension=0)
    assert up.ascend_option("a", at_cap, 0, {"insignia_tank_1": None}, {}, 10, 1, False) is None


def test_eidolon_option_needs_a_spare_copy():
    card = tank().with_(level=40, ascension=2, eidolon=2)
    assert up.eidolon_option("a", card, 0, 5) is None
    assert up.eidolon_option("a", card.with_(eidolon=6), 2, 5) is None
    opt = up.eidolon_option("a", card, 1, 5)
    assert opt.label == "feed copy e2 to e3" and opt.gain > 0 and opt.stars == 5 and opt.ready


def test_mod_swaps_take_the_best_spare_and_never_reuse_it():
    weak = mod("ez", 5, atkPct=0.01)
    strong = mod("fl", 5, atkPct=0.4, atk=50.0)
    card = Card("dps", "divine", 80, 6, 0, mods=(weak, weak, weak))
    other = Card("dps", "divine", 80, 6, 0, mods=(weak, weak, weak))
    swaps = up.mod_swaps([("one", card), ("two", other)], [strong], limit=3)
    assert len(swaps) == 1 and swaps[0].stars == 0 and swaps[0].ready
    assert swaps[0].label == "swap ez5 for fl5" and swaps[0].gain > 0
    assert up.mod_swaps([("one", card)], [mod("ez", 5, atkPct=0.0)]) == []


def test_best_mod_loadout_finds_a_synergy_a_greedy_swap_would_miss():
    # hd + ht + fl together trigger the "pindown" triple combo (b.COMBOS), each one
    # alone barely moves bp, so a one-swap-at-a-time search would not reach for it.
    card = Card("cc", "divine", 80, 6, 0, mods=())
    weak = mod("rx", 1, atkPct=0.0)  # a type with no fixed effect and no combo here: the floor
    market = {
        "hd": (mod("hd", 5, atkPct=0.0), 1000.0),
        "ht": (mod("ht", 5, atkPct=0.0), 1000.0),
        "fl": (mod("fl", 5, atkPct=0.0), 1000.0),
        "rx": (weak, 10.0),
    }
    best = up.best_mod_loadout("gatari", card, market)
    assert best is not None
    assert set(best.label.removeprefix("mods ").replace("5", "").split("+")) == {"hd", "ht", "fl"}
    assert best.stars == pytest.approx(3000.0) and best.gain > 0 and not best.ready
    assert "pindown" not in best.label  # the combo name itself is not shown, just the mods


def test_best_mod_loadout_is_free_for_what_is_already_equipped():
    good = mod("hd", 5, atkPct=0.0)
    card = Card("cc", "divine", 80, 6, 0, mods=(good,))
    market = {"hd": (mod("hd", 3, atkPct=0.0), 1000.0)}  # the market only has a worse one
    best = up.best_mod_loadout("gatari", card, market)
    assert best is None  # the owned hd5 already beats the market's hd3, nothing to add


def test_best_mod_loadout_returns_none_with_nothing_worth_buying():
    card = Card("cc", "divine", 80, 6, 0, mods=())
    assert up.best_mod_loadout("gatari", card, {}) is None


def test_rank_puts_free_first_then_cheapest_per_bp():
    ups = [
        up.Upgrade("a", "pricey", 100, 10_000),
        up.Upgrade("a", "cheap", 100, 1_000),
        up.Upgrade("a", "free small", 10, 0),
        up.Upgrade("a", "free big", 50, 0),
        up.Upgrade("a", "useless", 0, 5),
    ]
    assert [u.label for u in up.rank(ups)] == ["free big", "free small", "cheap", "pricey"]


def test_bp_table_style():
    team = [("camo", "dps", "divine", 28923), ("xootynator", "support", "mythic", 8605)]
    ups = [up.Upgrade("vaxei", "swap nc5 for dt5", 2048, 0),
           up.Upgrade("celybi", "level 60 to 70", 2388, 35880),
           up.Upgrade("xootynator", "a5 + level 70", 4434, 67115)]
    table = fmt.bp_table(team, ups, 63656, 26)
    lines = table.strip("`\n").splitlines()
    assert lines[0] == "team power 63,656 \u2665 account lv 26"
    assert table == table.lower() and "\u2014" not in table
    assert lines[3].endswith("free") and lines[4].endswith("\u260535,880")
    assert lines[-2] == "camo        dps      divine     28,923 bp"
    assert "wallet" not in table and "\u2713" not in table
    assert max(len(l) for l in lines) <= 56


def test_signature_cards_use_the_signature_class():
    raw = {
        "rarity": "divine", "level": 80, "ascension": 6, "eidolon": 4, "passive": None,
        "sig": {"id": "volley", "tier": "ssr"}, "mods": [],
        "player": {"cls": "cc", "passive": "thrifty"},
    }
    card = Card.from_api(raw)
    assert card.cls == "dps" and card.sig and card.passive is None
    assert Card.from_api({**raw, "sig": None}).cls == "cc"
    assert Card.from_api({**raw, "sig": {"id": "heatwave", "tier": "r"}}).cls == "cc"
