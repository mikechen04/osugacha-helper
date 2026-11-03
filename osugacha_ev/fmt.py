"""text output. everything lowercase, no em dashes, no wrapping lines."""

from __future__ import annotations

from datetime import datetime, timezone

from osugacha_ev.config import RUNS_PER_FUEL
from osugacha_ev.ev import EvRow
from osugacha_ev.store import Change

MAX_ROWS = 20
EV_FOOTER = "stars expected · item qty from drops.yaml · lbin"
PRICES_FOOTER = "lbin per unit · ! thin or swingy, may not hold"
SHAKY_NOTE = "! thin or swingy lbin, ev may be off"


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


def map_cell(row: EvRow) -> str:
    """map name in 12 chars, with * for estimated drops and ! for shaky lbin."""
    marks = ("*" if row.estimated else "") + ("!" if row.shaky else "")
    if not marks:
        return clip(row.map, 12)
    return row.map[: 12 - len(marks)] + marks


def ev_table(
    rows: list[EvRow],
    fuel_lbin: float,
    ts: float,
    *,
    missing: bool = False,
    fuel_shaky: bool = False,
) -> str:
    head = f"{'#':>2} {'map':<12} {'diff':<5} {'gross ev':>9} {'after fuel':>10}"
    fuel = star(fuel_lbin) + ("!" if fuel_shaky else "")
    lines = [
        f"fuel {fuel} (lbin) · {RUNS_PER_FUEL} runs · prices {stamp(ts)}",
        head,
        "-" * len(head),
    ]
    shown = rows[:MAX_ROWS]
    for i, row in enumerate(shown, 1):
        lines.append(
            f"{i:>2} {map_cell(row):<12} {clip(row.diff, 5):<5} "
            f"{star(row.gross):>9} {star(row.profit):>10}"
        )
    best = rows[0]
    lines += ["", f"best: {best.map} {best.diff} · {star(best.profit)} after fuel"]
    if any(r.estimated for r in shown):
        lines.append("* estimated drops")
    if fuel_shaky or any(r.shaky for r in shown):
        lines.append(SHAKY_NOTE)
    if missing:
        lines.append("missing lbin counted as 0")
    return lc(code(lines))


def prices_table(
    entries: list[tuple[str, float | None, Change | None, bool]], ts: float
) -> str:
    changes = [c for _, _, c, _ in entries if c]
    label = max(changes, key=lambda c: c.age).label if changes else "12h"
    head = f"{'item':<14} {'lbin':>8} {'vs ' + label:>7}  "
    lines = [f"per unit · prices {stamp(ts)}", head.rstrip(), "-" * len(head.rstrip())]
    for name, lbin, change, shaky in entries:
        lines.append(
            f"{clip(name, 14):<14} {star(lbin) if lbin is not None else 'n/a':>8} "
            f"{pct(change.pct) if change else '-':>7}" + (" !" if shaky else "")
        )
    return lc(code(lines))
