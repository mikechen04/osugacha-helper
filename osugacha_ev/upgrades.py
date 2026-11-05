"""what an upgrade costs and how much battle power it adds.

costs are the market value in stars of what you would spend, at lbin. an
upgrade is ready when you already hold the materials.
"""

from __future__ import annotations

import itertools
import math
from collections.abc import Mapping
from dataclasses import dataclass

from osugacha_ev import bp as bpmod
from osugacha_ev.bp import Card, Mod

MOD_SLOTS = 3

REPLAY_XP = {1: 1500, 2: 7500, 3: 30000}
FEED_STARS_PER_XP = {"low": 0.005, "high": 0.02}  # below level 80, from level 80
ACCOUNT_GATES = {5: 10, 6: 15, 7: 40, 13: 60, 19: 80}
ASC_TABLE = [  # to A1..A6: insignia tier, insignia count, boss trophies, stars
    (1, 5, 0, 50), (1, 10, 0, 100), (2, 8, 2, 200), (2, 15, 4, 400), (3, 15, 7, 2500), (3, 30, 12, 10000),
]
HIGH_TROPHIES = ["platinum_trophy", "diamond_trophy", "emerald_trophy"]
HIGH_TROPHY_COUNT = [3, 4, 5, 6, 8, 10]
HIGH_INSIGNIA_COUNT = [2, 2, 3, 3, 4, 4]
HIGH_STARS_BASE = [5e5, 6e5, 75e4, 9e5, 11e5, 13e5]


@dataclass(frozen=True)
class Upgrade:
    card: str
    label: str
    gain: int
    stars: float
    ready: bool = False

    @property
    def per_bp(self) -> float:
        return self.stars / self.gain if self.gain > 0 else math.inf


def js_round(x: float) -> int:
    return bpmod.js_round(x)


def ascension_gate(target: int) -> int:
    level = 1
    for asc, need in ACCOUNT_GATES.items():
        if asc <= target:
            level = max(level, need)
    return level


def ascension_cost(cls: str, target: int) -> tuple[dict[str, int], int]:
    """(items, stars) to ascend a card to the target ascension."""
    if target > 6:
        n = min(target, bpmod.MAX_ASC) - 6 - 1
        tier, step = divmod(n, 6)
        stars = 100000 if n == 0 else js_round(HIGH_STARS_BASE[step] * (tier + 1) * (2 if tier >= 1 else 0.75))
        return {f"insignia_{cls}_4": HIGH_INSIGNIA_COUNT[step], HIGH_TROPHIES[tier]: HIGH_TROPHY_COUNT[step]}, stars
    insignia_tier, count, trophies, stars = ASC_TABLE[target - 1]
    items = {f"insignia_{cls}_{insignia_tier}": count}
    if trophies:
        items["boss_trophy"] = trophies
    return items, stars


def feed_stars(level: int, xp: int, amount: int) -> int:
    """stars the game charges for feeding xp into a card."""
    amount = max(0, int(amount))
    below = min(amount, max(0, bpmod.xp_between(level, 80) - xp)) if level < 80 else 0
    return max(0, math.ceil(below * FEED_STARS_PER_XP["low"] + (amount - below) * FEED_STARS_PER_XP["high"] - 1e-9))


def replay_rate(prices: Mapping[str, float | None]) -> float | None:
    """cheapest stars per xp across the replay tiers."""
    rates = [prices[f"replay_{t}"] / xp for t, xp in REPLAY_XP.items() if prices.get(f"replay_{t}")]
    return min(rates) if rates else None


def owned_xp(inventory: Mapping[str, int]) -> int:
    return sum(inventory.get(f"replay_{t}", 0) * xp for t, xp in REPLAY_XP.items())


def level_option(
    name: str, card: Card, xp: int, target: int, prices, inventory, wallet: float
) -> Upgrade | None:
    if target <= card.level:
        return None
    need = bpmod.xp_between(card.level, target) - xp
    rate = replay_rate(prices)
    if need <= 0 or rate is None:
        return None
    fee = feed_stars(card.level, xp, need)
    gain = bpmod.battle_power(card.with_(level=target)) - bpmod.battle_power(card)
    ready = owned_xp(inventory) >= need and wallet >= fee
    return Upgrade(name, f"level {card.level} to {target}", gain, need * rate + fee, ready)


def ascend_option(name: str, card: Card, level_xp: int, prices, inventory, wallet, account_level: int,
                  with_levels: bool) -> Upgrade | None:
    target = card.ascension + 1
    if target > bpmod.MAX_ASC or card.level < bpmod.level_cap(card.ascension):
        return None
    if account_level < ascension_gate(target):
        return None
    items, stars = ascension_cost(card.cls, target)
    cost = float(stars)
    for item, qty in items.items():
        price = prices.get(item)
        if price is None:
            return None
        cost += price * qty
    ready = wallet >= stars and all(inventory.get(i, 0) >= q for i, q in items.items())
    after = card.with_(ascension=target)
    label = f"ascend to a{target}"
    if with_levels:
        top = bpmod.level_cap(target)
        extra = level_option(name, after, 0, top, prices, inventory, wallet)
        if extra is None:
            return None
        cost += extra.stars
        ready = ready and extra.ready
        after = after.with_(level=top)
        label = f"a{target} + level {top}"
    gain = bpmod.battle_power(after) - bpmod.battle_power(card)
    return Upgrade(name, label, gain, cost, ready)


def eidolon_option(name: str, card: Card, spare_copies: int, copy_value: float) -> Upgrade | None:
    if card.eidolon >= 6 or spare_copies <= 0:
        return None
    gain = bpmod.battle_power(card.with_(eidolon=card.eidolon + 1)) - bpmod.battle_power(card)
    return Upgrade(name, f"feed copy e{card.eidolon} to e{card.eidolon + 1}", gain, copy_value, True)


def mod_swaps(cards: list[tuple[str, Card]], spares: list[Mod], limit: int = 4) -> list[Upgrade]:
    """free mod changes: repeatedly take the single best swap across the team."""
    cards = [(n, c) for n, c in cards]
    pool = list(spares)
    found: list[Upgrade] = []
    for _ in range(limit):
        best = None
        for idx, (name, card) in enumerate(cards):
            now = bpmod.battle_power(card)
            slots = list(range(len(card.mods))) + ([len(card.mods)] if len(card.mods) < 3 else [])
            for slot in slots:
                for mod in pool:
                    mods = list(card.mods)
                    if slot < len(mods):
                        mods[slot] = mod
                    else:
                        mods.append(mod)
                    gain = bpmod.battle_power(card.with_(mods=tuple(mods))) - now
                    if best is None or gain > best[0]:
                        best = (gain, idx, slot, mod, mods)
        if best is None or best[0] <= 0:
            break
        gain, idx, slot, mod, mods = best
        name, card = cards[idx]
        old = card.mods[slot] if slot < len(card.mods) else None
        label = f"swap {old.type}{old.rarity}" if old else "add"
        label += f" for {mod.type}{mod.rarity}"
        found.append(Upgrade(name, label, gain, 0.0, True))
        cards[idx] = (name, card.with_(mods=tuple(mods)))
        pool.remove(mod)
    return found


def best_mod_loadout(
    name: str, card: Card, market: Mapping[str, tuple[Mod, float]], slots: int = MOD_SLOTS
) -> Upgrade | None:
    """search every combo of up to `slots` mod types for the one that adds the most bp.

    `market` maps mod type -> (the cheapest one on sale at its best rarity, its price).
    a type the card already carries at an equal or better rarity is free: there is no
    reason to buy another. this is a full search, not a greedy one, so it finds synergy
    combos a one-swap-at-a-time search would miss (two mods are often weaker alone than
    the pair bonus they unlock together).
    """
    pool: dict[str, tuple[Mod, float]] = dict(market)
    for mod in card.mods:
        have = pool.get(mod.type)
        if have is None or mod.rarity >= have[0].rarity:
            pool[mod.type] = (mod, 0.0)
    types = list(pool)
    now = bpmod.battle_power(card)
    best: tuple[int, tuple[str, ...]] | None = None
    for r in range(1, min(slots, len(types)) + 1):
        for combo in itertools.combinations(types, r):
            mods = tuple(pool[t][0] for t in combo)
            gain = bpmod.battle_power(card.with_(mods=mods)) - now
            if best is None or gain > best[0]:
                best = (gain, combo)
    if best is None or best[0] <= 0:
        return None
    gain, combo = best
    cost = sum(pool[t][1] for t in combo)
    label = "mods " + "+".join(f"{t}{pool[t][0].rarity}" for t in combo)
    return Upgrade(name, label, gain, cost, cost <= 0)


def rank(options: list[Upgrade]) -> list[Upgrade]:
    """free upgrades first by gain, then the cheapest per battle power."""
    useful = [o for o in options if o.gain > 0]
    free = sorted((o for o in useful if o.stars <= 0), key=lambda o: -o.gain)
    paid = sorted((o for o in useful if o.stars > 0), key=lambda o: o.per_bp)
    return free + paid
