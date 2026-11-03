"""text output. everything lowercase, no em dashes, no wrapping lines."""

from __future__ import annotations

from datetime import datetime, timezone

from osugacha_ev.ev import EvRow
from osugacha_ev.store import Change

MAX_ROWS = 20


def lc(text: str) -> str:
    return text.lower().replace("—", "-").replace("–", "-")


def num(value: float) -> str:
    return f"{round(value):,}"


def pct(value: float) -> str:
    if round(value, 1) == 0:
        return "0.0%"
    return f"{value:+.1f}%"


def stamp(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%m/%d %H:%M utc")


def clip(text: str, width: int) -> str:
    return text if len(text) <= width else text[: width - 1].rstrip() + "."


def code(lines: list[str]) -> str:
    return "```\n" + "\n".join(lines) + "\n```"


def ev_table(rows: list[EvRow]) -> str:
    lines = [f"{'#':>2} {'map':<12} {'diff':<5} {'gross ev':>8} {'profit':>7}"]
    for i, row in enumerate(rows[:MAX_ROWS], 1):
        name = row.map[:11] + "*" if row.estimated else clip(row.map, 12)
        lines.append(
            f"{i:>2} {name:<12} {clip(row.diff, 5):<5} {num(row.gross):>8} {num(row.profit):>7}"
        )
    if any(r.estimated for r in rows[:MAX_ROWS]):
        lines.append("* estimated drops")
    return lc(code(lines))


def ev_footer(fuel_lbin: float, ts: float) -> str:
    return lc(f"fuel lbin {num(fuel_lbin)} | {stamp(ts)}")


def prices_table(entries: list[tuple[str, float | None, Change | None]]) -> str:
    ages = [c.age for _, _, c in entries if c]
    label = max((c for _, _, c in entries if c), key=lambda c: c.age).label if ages else "12h"
    lines = [f"{'item':<14} {'lbin':>7} {'vs ' + label:>7}"]
    for name, lbin, change in entries:
        lines.append(
            f"{clip(name, 14):<14} {num(lbin) if lbin is not None else 'n/a':>7} "
            f"{pct(change.pct) if change else '-':>7}"
        )
    return lc(code(lines))


def prices_footer(ts: float) -> str:
    return lc(f"lbin per unit | {stamp(ts)}")
