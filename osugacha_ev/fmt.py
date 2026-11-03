"""text output. everything lowercase, no em dashes, no wrapping lines."""

from __future__ import annotations

from datetime import datetime, timezone

from osugacha_ev.config import RUNS_PER_FUEL
from osugacha_ev.ev import EvRow
from osugacha_ev.store import Change

MAX_ROWS = 20
EV_FOOTER = "stars expected · item qty from drops.yaml · lbin"
PRICES_FOOTER = "lbin per unit · buy it now only"


def lc(text: str) -> str:
    return text.lower().replace("—", "-").replace("–", "-")


def num(value: float) -> str:
    return f"{round(value):,}"


def star(value: float) -> str:
    return f"★{num(value)}"


def pct(value: float) -> str:
    if round(value, 1) == 0:
        return "0.0%"
    return f"{value:+.1f}%"


def stamp(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%H:%M utc")


def clip(text: str, width: int) -> str:
    return text if len(text) <= width else text[: width - 1].rstrip() + "."


def code(lines: list[str]) -> str:
    return "```\n" + "\n".join(lines) + "\n```"


def ev_table(rows: list[EvRow], fuel_lbin: float, ts: float, *, missing: bool = False) -> str:
    head = f"{'#':>2} {'map':<12} {'diff':<5} {'gross ev':>9} {'after fuel':>10}"
    lines = [
        f"fuel {star(fuel_lbin)} (lbin) · {RUNS_PER_FUEL} runs · prices {stamp(ts)}",
        head,
        "-" * len(head),
    ]
    for i, row in enumerate(rows[:MAX_ROWS], 1):
        name = row.map[:11] + "*" if row.estimated else clip(row.map, 12)
        lines.append(
            f"{i:>2} {name:<12} {clip(row.diff, 5):<5} {star(row.gross):>9} {star(row.profit):>10}"
        )
    best = rows[0]
    lines += ["", f"best: {best.map} {best.diff} · {star(best.profit)} after fuel"]
    if any(r.estimated for r in rows[:MAX_ROWS]):
        lines.append("* estimated drops")
    if missing:
        lines.append("missing lbin counted as 0")
    return lc(code(lines))


def prices_table(
    entries: list[tuple[str, float | None, Change | None]], ts: float
) -> str:
    changes = [c for _, _, c in entries if c]
    label = max(changes, key=lambda c: c.age).label if changes else "12h"
    head = f"{'item':<14} {'lbin':>8} {'vs ' + label:>7}"
    lines = [f"per unit · prices {stamp(ts)}", head, "-" * len(head)]
    for name, lbin, change in entries:
        lines.append(
            f"{clip(name, 14):<14} {star(lbin) if lbin is not None else 'n/a':>8} "
            f"{pct(change.pct) if change else '-':>7}"
        )
    return lc(code(lines))
