"""text output. everything lowercase, no em dashes, no wrapping lines."""

from __future__ import annotations

from datetime import datetime, timezone

from osugacha_ev.config import REFILL_STARS, RUNS_PER_FUEL
from osugacha_ev.ev import EvRow
from osugacha_ev.store import Change

MAX_ROWS = 20
MAX_PRICE_ROWS = 60
MAP_W = 15
SEP = " ♥ "
EV_FOOTER = "meow meow wruff arf awruf"
PRICES_FOOTER = "lbin per unit" + SEP + "! volatile lbin, may not hold"
SHAKY_NOTE = "! volatile lbin, ev may be inaccurate"


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


def refill_note(fuel_lbin: float | None) -> str | None:
    """a warning when buying fuel costs more than refilling stamina with stars."""
    if fuel_lbin is not None and fuel_lbin > REFILL_STARS:
        return f"note: {star(REFILL_STARS)} refill beats fuel lbin"
    return None


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
    skipped: str = "",
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
    if skipped:
        lines.append(f"not counted, unlikely to sell: {skipped}")
    if note := refill_note(fuel_lbin):
        lines.append(note)
    return lc(code(lines))


def units(n: int | None) -> str:
    if n is None:
        return "-"
    return str(n) if n < 1000 else f"{n / 1000:.1f}k"


def prices_table(
    entries: list[tuple[str, float | None, Change | None, bool, int | None]], ts: float
) -> str:
    """rows are (name, lbin, change, volatile, units gone in the last hour)."""
    changes = [c for _, _, c, _, _ in entries if c]
    label = max(changes, key=lambda c: c.age).label if changes else "6h"
    head = f"{'item':<16}  {'lbin':>10}  {'vs ' + label:>9}  {'gone/h':>6}"
    lines = [f"per unit{SEP}prices {stamp(ts)}", head, "-" * len(head)]
    hidden = max(0, len(entries) - MAX_PRICE_ROWS)
    for name, lbin, change, shaky, gone in entries[:MAX_PRICE_ROWS]:
        lines.append(
            f"{clip(name, 16):<16}  {star(lbin) if lbin is not None else 'n/a':>10}  "
            f"{pct(change.pct) if change else '-':>9}  {units(gone):>6}" + (" !" if shaky else "")
        )
    if hidden:
        lines.append(f"+{hidden} more items")
    fuel = next((lbin for name, lbin, _, _, _ in entries if name == "fuel"), None)
    if note := refill_note(fuel):
        lines.append(note)
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


def card_alert_text(alert, card: dict, rarity: str) -> tuple[str, str, str]:
    """title, description and footer for a card undercut ping."""
    listing = alert.listing
    lines = []
    if card.get("_player"):
        lines.append(f"card   {card['_player'].lower()}")
    lines += [
        f"price  {star(listing.price)}",
        f"next   {star(alert.next_lbin)}",
        f"below  {alert.below_pct:.1f}%{SEP}{ago(alert.age)}",
    ]
    if card.get("_seller"):
        lines.append(f"seller {card['_seller'].lower()}")
    detail = [f"lvl {card.get('level', 1)}"]
    if card.get("ascension"):
        detail.append(f"asc {card['ascension']}")
    if card.get("eidolon"):
        detail.append(f"eid {card['eidolon']}")
    if card.get("mods"):
        detail.append(f"{len(card['mods'])} mods")
    if card.get("sig"):
        detail.append("signature")
    lines.append(SEP.join(detail))
    if card.get("serialNo"):
        lines.append(f"serial #{card['serialNo']}")
    return (
        lc(f"{rarity} card undercut"),
        lc(code(lines)),
        lc("buy it now" + SEP + "/cardalerts off to stop"),
    )


def span_text(seconds: float) -> str:
    days, rest = divmod(int(seconds), 86400)
    hours = rest // 3600
    return f"{days}d {hours}h" if days else f"{hours}h"


def hour_rows(rows: list[tuple[int, float, float, float | None]]) -> list[str]:
    """rows are (utc hour, mean lbin, percent vs overall mean, units gone a day)."""
    return [
        f"{h:02d}:00  {star(avg):>9}  {pct(vs):>7}  {('%.0f' % gone) if gone is not None else '-':>5}"
        for h, avg, vs, gone in rows
    ]


def besttime_table(
    name: str,
    span: float,
    sell: list[tuple[int, float, float, float | None]],
    buy: list[tuple[int, float, float, float | None]],
    busiest: list[int],
    rough: bool,
) -> str:
    head = f"{'hour':<5}  {'avg lbin':>9}  {'vs avg':>7}  {'gone/d':>5}"
    lines = [f"{name}{SEP}{span_text(span)} of data{SEP}utc", head, "-" * len(head), "sell high"]
    lines += hour_rows(sell)
    if buy:
        lines += ["buy low"] + hour_rows(buy)
    if busiest:
        lines.append("busiest: " + " ".join(f"{h:02d}:00" for h in busiest))
    if rough:
        lines.append("rough, under 3 days of data")
    return lc(code(lines))


def bp_table(team, options, team_power: float, account_level: int) -> str:
    """team is (name, class, rarity, bp) rows, options are upgrades.Upgrade."""
    head = f"{'#':>2}  {'card':<10}  {'upgrade':<18}  {'+bp':>6}  {'cost':>8}"
    lines = [f"team power {team_power:,}{SEP}account lv {account_level}", head, "-" * len(head)]
    for i, o in enumerate(options, 1):
        cost = "free" if o.stars <= 0 else star(o.stars)
        lines.append(
            f"{i:>2}  {clip(o.card, 10):<10}  {clip(o.label, 18):<18}  {'+' + format(o.gain, ','):>6}  {cost:>8}"
        )
    if not options:
        lines.append("nothing here adds bp right now")
    lines.append("")
    for name, cls, rarity, bp in team:
        lines.append(f"{clip(name, 10):<10}  {cls:<7}  {rarity:<9}  {bp:>6,} bp")
    return lc(code(lines))
