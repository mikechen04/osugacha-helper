"""names and ordering for every item the market sells (mods and cards excluded)."""

from __future__ import annotations

CLASS_ORDER = ["tank", "dps", "support", "cc"]
CLASS_SHORT = {"tank": "tank", "dps": "dps", "support": "supp", "cc": "mage"}
TROPHY_ORDER = ["boss_trophy", "platinum_trophy", "diamond_trophy", "emerald_trophy"]
REPLAY_NAMES = {"replay_1": "bronze replay", "replay_2": "silver replay", "replay_3": "gold replay"}


def _insignia(item_id: str) -> tuple[str, int] | None:
    parts = item_id.split("_")
    if len(parts) == 3 and parts[0] == "insignia" and parts[2].isdigit():
        return parts[1], int(parts[2])
    return None


def item_name(item_id: str) -> str:
    """a short lowercase name that fits the table."""
    if item_id in REPLAY_NAMES:
        return REPLAY_NAMES[item_id]
    parsed = _insignia(item_id)
    if parsed:
        cls, tier = parsed
        return f"{CLASS_SHORT.get(cls, cls)} insig {tier}"
    return item_id.replace("_", " ")


def item_order(item_id: str) -> tuple:
    """fuel, replays, fragments, trophies, then insignia by class and tier."""
    if item_id == "fuel":
        return (0, "", 0)
    if item_id.startswith("replay_"):
        return (1, item_id, 0)
    if item_id == "mod_fragment":
        return (2, "", 0)
    if item_id in TROPHY_ORDER:
        return (3, "", TROPHY_ORDER.index(item_id))
    parsed = _insignia(item_id)
    if parsed:
        cls, tier = parsed
        rank = CLASS_ORDER.index(cls) if cls in CLASS_ORDER else len(CLASS_ORDER)
        return (4, "", rank * 100 + tier)
    return (9, item_id, 0)


def sort_items(item_ids) -> list[str]:
    return sorted(dict.fromkeys(item_ids), key=item_order)
