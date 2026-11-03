"""battle power, ported from the game's own rules.

the numbers and formulas come from the public client code at osugacha.com, so
they match what the site shows as long as the game is not rebalanced. when the
game changes, update the tables here.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any


def js_round(x: float) -> int:
    """javascript's Math.round: halves go up."""
    return math.floor(x + 0.5)


RARITIES = ["common", "uncommon", "rare", "epic", "legendary", "mythic", "divine", "restricted"]
RARITY_ORDER = {name: i for i, name in enumerate(RARITIES)}
RARITY_BASE = {
    "common": 62, "uncommon": 64, "rare": 65.5, "epic": 67,
    "legendary": 68.5, "mythic": 70, "divine": 72, "restricted": 72,
}

# class stat multipliers
CLASSES = {
    "tank": {"atk": 0.85, "hp": 1.35, "spd": 0.94, "def": 1.45, "crit": 0.0},
    "dps": {"atk": 1.02, "hp": 1.36, "spd": 1.04, "def": 0.85, "crit": 0.04},
    "support": {"atk": 0.95, "hp": 1.45, "spd": 1.12, "def": 1.05, "crit": 0.0},
    "cc": {"atk": 0.95, "hp": 1.3, "spd": 1.06, "def": 1.02, "crit": 0.0},
}
DEF_BASE = 1.6
CRIT_RATE_BASE = 0.05
CRIT_DMG_BASE = 0.5
SPD_PER_LEVEL = 0.0025
SIG_BONUS = 0.03
SOLO_DPS = 0.25

# how each class weighs damage, toughness, speed and healing in the power score
CLASS_WEIGHT = {
    "dps": {"dmg": 0.84, "tough": 0.93, "spd": 0.24, "heal": 0.0},
    "tank": {"dmg": 0.39, "tough": 1.98, "spd": 0.15, "heal": 0.0},
    "support": {"dmg": 0.47, "tough": 1.95, "spd": 0.4, "heal": 0.66},
    "cc": {"dmg": 0.95, "tough": 0.67, "spd": 0.75, "heal": 0.0},
}
CLASS_SCALE = {"dps": 0.87, "tank": 1.14, "support": 0.9, "cc": 1.09}
COMBO_DEFAULT = 0.03
COMBO_WEIGHT = {
    "dps": {"pindown": .083, "desperado": .057, "crit": .054, "ss": .053, "secondchance": .051,
            "overclock": .051, "lockdown": .047, "kiai": .047, "burst": .044, "storm": .042,
            "defensive": .04, "laststand": .04, "opening": .039, "assassin": .036,
            "juggernaut": .036, "executioner": .034, "firstaid": .03, "shatter": .026,
            "focus": .016, "conductor": .014, "glass": .009, "tempo": .007, "riposte": .006,
            "contagion": .005, "hex": -.003, "hypercarry": -.006, "fortress": -.023, "sustain": -.03},
    "tank": {"secondchance": .091, "riposte": .077, "conductor": .071, "pindown": .064,
             "assassin": .05, "lockdown": .046, "desperado": .044, "executioner": .043,
             "juggernaut": .04, "opening": .03, "firstaid": .026, "crit": .025, "defensive": .024,
             "focus": .023, "shatter": .023, "ss": .022, "overclock": .02, "laststand": .019,
             "fortress": .017, "tempo": .01, "storm": .009, "burst": .008, "hypercarry": .004,
             "hex": .002, "contagion": -.007, "glass": -.011, "sustain": -.025, "kiai": -.029},
    "support": {"pindown": .07, "executioner": .05, "secondchance": .046, "lockdown": .04,
                "laststand": .039, "sustain": .037, "tempo": .036, "kiai": .03, "desperado": .029,
                "crit": .024, "assassin": .022, "burst": .016, "ss": .016, "conductor": .015,
                "overclock": .011, "shatter": .009, "firstaid": .009, "opening": .009, "focus": .007,
                "riposte": .002, "contagion": .001, "hypercarry": -.004, "juggernaut": -.005,
                "hex": -.008, "fortress": -.009, "storm": -.017, "defensive": -.025, "glass": -.119},
    "cc": {"pindown": .119, "contagion": .07, "desperado": .05, "hex": .05, "lockdown": .047,
           "assassin": .045, "secondchance": .04, "laststand": .035, "overclock": .034,
           "juggernaut": .033, "opening": .032, "conductor": .031, "shatter": .03, "kiai": .029,
           "ss": .029, "burst": .028, "executioner": .027, "crit": .024, "hypercarry": .016,
           "firstaid": .012, "focus": .011, "defensive": .009, "storm": .001, "riposte": .001,
           "tempo": 0, "fortress": -.014, "glass": -.025, "sustain": -.035},
}

# mod combos: id -> the mod types that make it, in the game's order
COMBOS: list[tuple[str, tuple[str, ...]]] = [
    ("burst", ("hd", "dt")), ("crit", ("hd", "hr")), ("hypercarry", ("hd", "dt", "hr")),
    ("assassin", ("hd", "dt", "fl")), ("defensive", ("ez", "nf", "ht")), ("focus", ("hd", "fl")),
    ("sustain", ("ez", "ht")), ("fortress", ("nf", "ht")), ("glass", ("sd", "hr")),
    ("hex", ("hd", "ht")), ("tempo", ("dt", "rx")), ("kiai", ("nc", "dt")),
    ("shatter", ("so", "fl")), ("storm", ("so", "nc")), ("ss", ("pf", "hr")),
    ("conductor", ("rx", "nc", "dt")), ("executioner", ("sd", "pf", "fl")),
    ("firstaid", ("ez", "nf")), ("juggernaut", ("nf", "so")), ("pindown", ("hd", "ht", "fl")),
    ("lockdown", ("ht", "fl")), ("opening", ("so", "rx")), ("overclock", ("dt", "fl")),
    ("laststand", ("nf", "sd")), ("contagion", ("hd", "ht", "nc")), ("riposte", ("ht", "so", "fl")),
    ("secondchance", ("ez", "nf", "rx")), ("desperado", ("sd", "dt", "ez")),
]

U = {
    "critRate": 0.05, "hypercarryCrit": 0.1, "overclockCrit": 0.04, "critVsDebuffed": 0.2,
    "glassDmg": 0.36, "shatterDmg": 0.1, "ssCrit": 0.05, "ssCritDmg": 0.2,
    "executionerDmg": 0.08, "executionerLowDmg": 0.25, "juggernautAtk": 0.004,
}
EIDOLON = {"passiveMult": 1.3, "dpsE1Crit": 0.1, "dpsE4CritDmg": 0.15, "supportE1Heal": 0.1}
DEADEYE = {"rate": 0.08, "dmg": 0.25, "vsLow": 0.1, "vsLowDmg": 0.2}
# how often each situation applies when the power score estimates damage
SITUATION = {"debuffed": 0.5, "low": 0.35, "broken": 0.2, "single": 0.75, "highHp": 0.5,
             "ssUp": 0.5, "executeLow": 0.2}
MOD_RARITY_SCALE = {1: 0.4, 2: 0.55, 3: 0.7, 4: 0.85, 5: 1.0}

# levels and ascension
ASC_LEVELS = [20, 30, 40, 50, 60, 70, 80] + [80 + 5 * (t + 1) for t in range(3 * 6)]
MAX_ASC = len(ASC_LEVELS) - 1
MAX_LEVEL = ASC_LEVELS[-1]
LEVEL_GROWTH = 6 ** (10 / 79)
POST_ASC_GROWTH = (0.5, 0.4, 0.3)


def level_cap(ascension: int) -> int:
    return ASC_LEVELS[max(0, min(MAX_ASC, ascension))]


def xp_to_next(level: int) -> int:
    """xp to get from this level to the next."""
    if level >= MAX_LEVEL:
        return 0
    base = js_round(200 + 60 * level + level**4 / 380)
    if level >= 80:
        base *= 5 * (2 if level >= 110 else 1)
    return base


def xp_between(start: int, end: int) -> int:
    return sum(xp_to_next(level) for level in range(start, end))


def _post_ascension(level: float) -> float:
    total = 1.0
    for i, weight in enumerate(POST_ASC_GROWTH):
        total += weight * max(0.0, min(1.0, (level - 80 - 30 * i) / 30))
    return total


def stat_mult(level: int, ascension: int) -> float:
    if ascension > 6:
        return stat_mult(80, 6) * _post_ascension(level)
    return LEVEL_GROWTH ** ((max(1, min(100, level)) - 1) / 10) * (1 + ascension / 30)


def speed_level(level: int, ascension: int) -> int:
    return min(level, 80) if ascension > 6 else level


@dataclass(frozen=True)
class Mod:
    type: str
    rarity: int
    stats: tuple[tuple[str, float], ...]  # the main stat then every substat

    @classmethod
    def from_api(cls, raw: Mapping[str, Any]) -> "Mod":
        lines = [(raw["main"]["stat"], float(raw["main"]["value"]))]
        lines += [(s["stat"], float(s["value"])) for s in raw.get("subs", [])]
        return cls(raw["type"], int(raw["rarity"]), tuple(lines))


@dataclass(frozen=True)
class Card:
    cls: str
    rarity: str
    level: int
    ascension: int
    eidolon: int
    passive: str | None = None
    sig: bool = False
    mods: tuple[Mod, ...] = ()

    @classmethod
    def from_api(cls, raw: Mapping[str, Any], mods: Iterable[Mod] | None = None) -> "Card":
        player = raw.get("player") or {}
        sig = bool(raw.get("sig"))
        passive = None if sig else (raw.get("passive") or player.get("passive"))
        return cls(
            cls=player.get("cls") or "dps",
            rarity=raw["rarity"],
            level=int(raw["level"]),
            ascension=int(raw["ascension"]),
            eidolon=int(raw["eidolon"]),
            passive=passive,
            sig=sig,
            mods=tuple(mods) if mods is not None else tuple(Mod.from_api(m) for m in raw.get("mods", [])),
        )

    def with_(self, **changes: Any) -> "Card":
        return Card(**{**self.__dict__, **changes})


@dataclass
class Stats:
    atk: float
    maxHp: float
    defense: float
    spd: float
    critRate: float
    critDmg: float
    guardDmg: float
    outHeal: float
    atkPct: float = 0.0
    combos: list[str] = field(default_factory=list)
    fx: dict[str, float] = field(default_factory=dict)
    passiveMult: float = 1.0


def _jsr4(x: float) -> float:
    return js_round(x * 1e4) / 1e4


def combos_for(mod_types: Iterable[str]) -> list[str]:
    have = set(mod_types)
    triple = next((cid for cid, t in COMBOS if len(t) == 3 and all(m in have for m in t)), None)
    if triple:
        return [triple]
    return [cid for cid, t in COMBOS if len(t) == 2 and all(m in have for m in t)]


def mod_bag(card: Card) -> tuple[dict[str, float], dict[str, float], list[str], float]:
    """the stat bag, effect totals, combos and passive multiplier from a card's mods."""
    bag: dict[str, float] = {}
    fx = {k: 0.0 for k in ("singleDmg", "dmgVsLow", "dmgVsDebuffed", "dmgVsBroken", "pfCritDmg")}

    def add(stat: str, value: float) -> None:
        bag[stat] = bag.get(stat, 0.0) + value

    for mod in card.mods:
        for stat, value in mod.stats:
            add(stat, value)
        scale = MOD_RARITY_SCALE[mod.rarity]

        def a(x: float) -> float:
            return _jsr4(x * scale)

        match mod.type:
            case "ez":
                add("hpPct", a(0.1)); add("outHeal", a(0.1))
            case "ht":
                add("defPct", a(0.12))
            case "hr":
                add("critRate", a(0.06))
            case "sd":
                fx["dmgVsLow"] += a(0.2); add("hpPct", -a(0.08))
            case "dt":
                add("spd", a(6))
            case "hd":
                fx["dmgVsDebuffed"] += a(0.1)
            case "fl":
                fx["singleDmg"] += a(0.12)
            case "pf":
                add("critDmg", a(0.2)); fx["pfCritDmg"] += a(0.1)
            case "so":
                fx["dmgVsBroken"] += a(0.15)

    combos = combos_for(m.type for m in card.mods)
    if "crit" in combos:
        add("critRate", U["critRate"])
    if "hypercarry" in combos:
        add("critRate", U["hypercarryCrit"])
    if "fortress" in combos:
        add("defPct", 0.15)
    if "glass" in combos:
        add("hpPct", -0.15)
    if "overclock" in combos:
        add("critRate", U["overclockCrit"])

    passive_mult = EIDOLON["passiveMult"] if card.eidolon >= 2 else 1.0
    if card.passive == "deadeye":
        add("critRate", DEADEYE["rate"] * passive_mult)
        add("critDmg", DEADEYE["dmg"] * passive_mult)
    if card.cls == "dps" and card.eidolon >= 1:
        add("critRate", EIDOLON["dpsE1Crit"])
    if card.cls == "dps" and card.eidolon >= 4:
        add("critDmg", EIDOLON["dpsE4CritDmg"])
    if card.cls == "support" and card.eidolon >= 1:
        add("outHeal", EIDOLON["supportE1Heal"])
    return bag, fx, combos, passive_mult


def _speed(card: Card, class_spd: float) -> float:
    order = max(0, RARITY_ORDER[card.rarity])
    return (100 + 0.5 * order) * class_spd * (1 + SPD_PER_LEVEL * max(0, speed_level(card.level, card.ascension) - 1))


def stats_for(card: Card, bag: Mapping[str, float] | None = None) -> Stats:
    k = CLASSES.get(card.cls, CLASSES["dps"])
    bag = bag or {}
    base = RARITY_BASE[card.rarity] * stat_mult(card.level, card.ascension) * (1 + SIG_BONUS if card.sig else 1)
    return Stats(
        atk=base * k["atk"] * (1 + bag.get("atkPct", 0.0)) + bag.get("atk", 0.0),
        maxHp=max(1.0, base * 22 * k["hp"] * (1 + bag.get("hpPct", 0.0)) + bag.get("hp", 0.0)),
        defense=base * DEF_BASE * k["def"] * (1 + bag.get("defPct", 0.0)) + bag.get("def", 0.0),
        spd=_speed(card, k["spd"]) + bag.get("spd", 0.0),
        critRate=CRIT_RATE_BASE + k["crit"] + bag.get("critRate", 0.0),
        critDmg=CRIT_DMG_BASE + bag.get("critDmg", 0.0),
        guardDmg=bag.get("guardDmg", 0.0),
        outHeal=bag.get("outHeal", 0.0),
        atkPct=bag.get("atkPct", 0.0),
    )


def _situational(stats: Stats, passive: str | None) -> tuple[float, float, float]:
    """extra damage, crit rate and crit damage the power score assumes in a fight."""
    s = SITUATION
    fx = stats.fx
    dmg = fx["singleDmg"] * s["single"] + fx["dmgVsLow"] * s["low"] + fx["dmgVsDebuffed"] * s["debuffed"] + fx["dmgVsBroken"] * s["broken"]
    rate = crit_dmg = 0.0
    combos = stats.combos
    if "glass" in combos:
        dmg += U["glassDmg"]
    if "executioner" in combos:
        dmg += U["executionerDmg"] + U["executionerLowDmg"] * s["executeLow"]
    if "shatter" in combos:
        dmg += U["shatterDmg"] * s["broken"]
    if "ss" in combos:
        rate += U["ssCrit"] * s["ssUp"]
        crit_dmg += U["ssCritDmg"] * s["ssUp"]
    if "crit" in combos:
        crit_dmg += U["critVsDebuffed"] * s["debuffed"]
    crit_dmg += fx["pfCritDmg"] * s["highHp"]
    if passive == "deadeye":
        rate += DEADEYE["vsLow"] * stats.passiveMult * s["low"]
        crit_dmg += DEADEYE["vsLowDmg"] * stats.passiveMult * s["low"]
    return dmg, rate, crit_dmg


def _offense(stats: Stats, extra: tuple[float, float, float] = (0.0, 0.0, 0.0)) -> float:
    dmg, rate, crit_dmg = extra
    atk = stats.atk
    if "juggernaut" in stats.combos:
        atk += stats.maxHp * U["juggernautAtk"] * (1 + stats.atkPct)
    return (
        atk
        * (1 + dmg / (1 + stats.atkPct))
        * (1 + min(1.0, stats.critRate + rate) * (stats.critDmg + crit_dmg))
        * (1 + stats.guardDmg * 0.05)
    )


_TOUGH_PLAIN = 0.6 / DEF_BASE
_TOUGH_POWER = 1.8 / DEF_BASE


def _toughness(stats: Stats, level: int, k: float = _TOUGH_PLAIN) -> float:
    return math.sqrt(stats.maxHp * (9 / 22) * (1 + stats.defense * k / (200 + 10 * level)))


def _score(stats: Stats, level: int) -> float:
    return _offense(stats) * _toughness(stats, level) * (stats.spd / 100)


def _class_scale(cls: str, solo: bool) -> float:
    return CLASS_SCALE.get(cls, 1.0) * (1 + SOLO_DPS if cls == "dps" and solo else 1.0)


def battle_power(card: Card) -> int:
    """a card's battle power, with its mods, eidolons and combos counted."""
    bag, fx, combos, passive_mult = mod_bag(card)
    with_mods = stats_for(card, bag)
    with_mods.fx, with_mods.combos, with_mods.passiveMult = fx, combos, passive_mult
    plain = stats_for(card)
    level = speed_level(card.level, card.ascension)
    w = CLASS_WEIGHT.get(card.cls, CLASS_WEIGHT["dps"])
    base = _score(plain, level) * _class_scale(card.cls, True)
    ratio = (
        (_offense(with_mods, _situational(with_mods, card.passive)) / _offense(plain)) ** w["dmg"]
        * (_toughness(with_mods, level, _TOUGH_POWER) / _toughness(plain, level, _TOUGH_POWER)) ** w["tough"]
        * (with_mods.spd / plain.spd) ** w["spd"]
        * ((1 + with_mods.outHeal) / (1 + plain.outHeal)) ** w["heal"]
    )
    weights = COMBO_WEIGHT.get(card.cls, COMBO_WEIGHT["dps"])
    combo_mult = 1 + sum(weights.get(c, COMBO_DEFAULT) for c in combos)
    return js_round(base * ratio * (1 + 0.05 * card.eidolon) * combo_mult / 9)
