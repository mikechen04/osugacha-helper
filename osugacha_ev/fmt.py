"""text output. everything lowercase, no em dashes, no wrapping lines."""

from __future__ import annotations

from datetime import datetime, timezone

from osugacha_ev.config import RUNS_PER_FUEL
from osugacha_ev.ev import EvRow
from osugacha_ev.store import Change

MAX_ROWS = 20
MAP_W = 15
SEP = " ♥ "
EV_FOOTER = "meow meow wruff arf awruf"
PRICES_FOOTER = "lbin per unit" + SEP + "! thin or swingy, may not hold"
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
    """map name, with * for estimated drops and ! for shaky lbin."""
    marks = ("*" if row.estimated else "") + ("!" if row.shaky else "")
    if not marks:
        return clip(row.map, MAP_W)
    return row.map[: MAP_W - len(marks)] + marks


def ev_table(
    rows: list[EvRow],
    fuel_lbin: float,
    ts: float,
    *,
    missing: bool = False,
    fuel_shaky: bool = False,
) -> str:
    head = f"{'#':>2}  {'map':<{MAP_W}}  {'diff':<5}  {'gross ev':>10}  {'after fuel':>11}"
    fuel = star(fuel_lbin) + ("!" if fuel_shaky else "")
    lines = [
        f"fuel {fuel} (lbin){SEP}{RUNS_PER_FUEL} runs{SEP}prices {stamp(ts)}",
        head,
        "-" * len(head),
    ]
    shown = rows[:MAX_ROWS]
    for i, row in enumerate(shown, 1):
        lines.append(
            f"{i:>2}  {map_cell(row):<{MAP_W}}  {clip(row.diff, 5):<5}  "
            f"{star(row.gross):>10}  {star(row.profit):>11}"
        )
    best = rows[0]
    lines += ["", f"best: {best.map} {best.diff}{SEP}{star(best.profit)} after fuel"]
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
    label = max(changes, key=lambda c: c.age).label if changes else "6h"
    head = f"{'item':<16}  {'lbin':>10}  {'vs ' + label:>9}"
    lines = [f"per unit{SEP}prices {stamp(ts)}", head, "-" * len(head)]
    for name, lbin, change, shaky in entries:
        lines.append(
            f"{clip(name, 16):<16}  {star(lbin) if lbin is not None else 'n/a':>10}  "
            f"{pct(change.pct) if change else '-':>9}" + (" !" if shaky else "")
        )
    return lc(code(lines))


def ago(seconds: float) -> str:
    if seconds < 90:
        return f"{max(1, round(seconds))}s ago"
    return f"{round(seconds / 60)}m ago"


def alert_text(alert) -> tuple[str, str, str]:
    """title, description and footer for a fuel quicksell ping."""
    listing = alert.listing
    qty = f" x{listing.qty}" if listing.qty > 1 else ""
    lines = [
        f"lbin   {star(listing.unit)}{qty}",
        f"next   {star(alert.next_lbin)}",
        f"below  {alert.below_pct:.1f}%{SEP}{ago(alert.age)}",
    ]
    if listing.qty > 1:
        lines.insert(1, f"total  {star(listing.price)}")
    return (
        lc("fuel quicksell"),
        lc(code(lines)),
        lc("buy it now" + SEP + "/alerts off to stop"),
    )
