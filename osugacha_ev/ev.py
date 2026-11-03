"""fuel ev math. 1 fuel = 6 runs."""

from __future__ import annotations

from collections.abc import Collection
from dataclasses import dataclass

from osugacha_ev.config import RUNS_PER_FUEL, SELL_FEE, WARN_SHARE
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
    shaky: bool = False
    skipped: bool = False


def compute(
    entry: DiffDrops,
    lbins: dict[str, float | None],
    fuel_lbin: float,
    shaky: Collection[str] = (),
    skip: Collection[str] = (),
) -> EvRow:
    """per run ev = avg stars + sum(avg qty x lbin).

    the 2% market fee only applies to sold items, so stars are never discounted.
    an item with no lbin counts as 0 and is reported in `missing`. items in `skip` (nobody buys them) count as 0 too. the row is
    shaky when a thin or swingy item makes up a real share of the per run ev.
    """
    missing = []
    skipped = False
    values: dict[str, float] = {}
    for drop in entry.items:
        if drop.item in skip:
            skipped = True
            continue
        price = lbins.get(drop.item)
        if price is None:
            missing.append(drop.item)
            continue
        values[drop.item] = drop.avg * price
    item_run = sum(values.values())
    stars = entry.stars_avg * RUNS_PER_FUEL
    items = item_run * RUNS_PER_FUEL
    gross = stars + items
    after_fee = stars + items * (1 - SELL_FEE)
    per_run = entry.stars_avg + item_run
    flagged = sum(v for item, v in values.items() if item in shaky)
    return EvRow(
        map=entry.label,
        diff=entry.diff,
        gross=gross,
        after_fee=after_fee,
        profit=after_fee - fuel_lbin,
        estimated=entry.estimated,
        missing=tuple(missing),
        shaky=per_run > 0 and flagged / per_run >= WARN_SHARE,
        skipped=skipped,
    )


def rank(
    entries: list[DiffDrops],
    lbins: dict[str, float | None],
    fuel_lbin: float,
    shaky: Collection[str] = (),
    skip: Collection[str] = (),
) -> list[EvRow]:
    rows = [compute(e, lbins, fuel_lbin, shaky, skip) for e in entries]
    return sorted(rows, key=lambda r: r.profit, reverse=True)
