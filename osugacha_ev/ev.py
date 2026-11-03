"""fuel ev math. 1 fuel = 6 runs."""

from __future__ import annotations

from dataclasses import dataclass

from osugacha_ev.config import RUNS_PER_FUEL, SELL_FEE
from osugacha_ev.drops import DiffDrops


@dataclass(frozen=True)
class EvRow:
    map: str
    diff: str
    gross: float
    after_fee: float
    profit: float
    estimated: bool
    missing: tuple[str, ...] = ()


def compute(entry: DiffDrops, lbins: dict[str, float | None], fuel_lbin: float) -> EvRow:
    """per run ev = avg stars + sum(avg qty x lbin).

    the 2% market fee only applies to sold items, so stars are never discounted.
    an item with no lbin counts as 0 and is reported in `missing`.
    """
    missing = []
    item_run = 0.0
    for drop in entry.items:
        price = lbins.get(drop.item)
        if price is None:
            missing.append(drop.item)
            continue
        item_run += drop.avg * price
    stars = entry.stars_avg * RUNS_PER_FUEL
    items = item_run * RUNS_PER_FUEL
    gross = stars + items
    after_fee = stars + items * (1 - SELL_FEE)
    return EvRow(
        map=entry.label,
        diff=entry.diff,
        gross=gross,
        after_fee=after_fee,
        profit=after_fee - fuel_lbin,
        estimated=entry.estimated,
        missing=tuple(missing),
    )


def rank(entries: list[DiffDrops], lbins: dict[str, float | None], fuel_lbin: float) -> list[EvRow]:
    rows = [compute(e, lbins, fuel_lbin) for e in entries]
    return sorted(rows, key=lambda r: r.profit, reverse=True)
