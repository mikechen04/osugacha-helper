"""shared logic for the bot and the terminal commands."""

from __future__ import annotations

import time
from dataclasses import dataclass

from osugacha_ev import ev as evmath
from osugacha_ev import fmt
from osugacha_ev.api import OsuGachaClient
from osugacha_ev.config import SNAPSHOT_EVERY, SWING_PCT, Settings
from osugacha_ev.drops import DropTable, load_drops
from osugacha_ev.prices import PriceBook, PriceService
from osugacha_ev.store import SnapshotStore

FUEL = "fuel"


@dataclass(frozen=True)
class Report:
    title: str
    description: str
    footer: str


class App:
    def __init__(self, settings: Settings, *, client: OsuGachaClient | None = None):
        self.settings = settings
        self.client = client or OsuGachaClient(settings.api_key)
        self.table: DropTable = load_drops(settings.drops_file)
        self.store = SnapshotStore(settings.db_file)
        self.prices = PriceService(self.client)

    async def aclose(self) -> None:
        await self.client.aclose()
        self.store.close()

    def _tracked(self) -> list[str]:
        ids = self.table.item_ids
        return [FUEL] + [i for i in ids if i != FUEL]

    async def ev_report(self) -> Report:
        if not self.table.entries:
            return Report("ev", fmt.lc("no drops in drops.yaml yet"), "")
        book = await self.prices.get(self._tracked())
        fuel = book.lbins.get(FUEL)
        if fuel is None:
            return Report("ev", fmt.lc("no fuel listings right now"), "")
        shaky = self.shaky(book)
        rows = evmath.rank(self.table.entries, book.lbins, fuel, shaky)
        return Report(
            title=fmt.lc("map ev vs fuel"),
            description=fmt.ev_table(
                rows,
                fuel,
                book.fetched_at,
                missing=any(r.missing for r in rows),
                fuel_shaky=FUEL in shaky,
            ),
            footer=fmt.EV_FOOTER,
        )

    def shaky(self, book: PriceBook, now: float | None = None) -> set[str]:
        """items with thin listings, or whose lbin moved a lot vs 6h ago."""
        now = now if now is not None else time.time()
        flagged = book.thin()
        for item, lbin in book.lbins.items():
            change = self.store.change(item, lbin, now)
            if change and abs(change.pct) >= SWING_PCT:
                flagged.add(item)
        return flagged

    def _label(self, item_id: str) -> str:
        if item_id.startswith("mod:"):
            _, mod_type, star = item_id.split(":")
            return f"{mod_type} {star}★"
        return self.table.names.get(item_id, item_id.replace("_", " "))

    async def prices_report(self) -> Report:
        ids = [FUEL] + [i for i in self.table.names if i != FUEL]
        book = await self.prices.get(ids)
        now = time.time()
        shaky = self.shaky(book, now)
        entries = [
            (
                self._label(i),
                book.lbins[i],
                self.store.change(i, book.lbins[i], now),
                i in shaky,
            )
            for i in ids
        ]
        return Report(
            title=fmt.lc("lbin prices"),
            description=fmt.prices_table(entries, book.fetched_at),
            footer=fmt.PRICES_FOOTER,
        )

    async def snapshot(self, *, force: bool = False) -> int:
        """store an lbin snapshot unless one was taken in the last 15 min."""
        last = self.store.last_snapshot_ts()
        if not force and last is not None and time.time() - last < SNAPSHOT_EVERY - 60:
            return 0
        book = await self.prices.get(self._tracked(), force=True)
        return self.store.add(book.lbins, book.fetched_at)
