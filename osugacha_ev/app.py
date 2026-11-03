"""shared logic for the bot and the terminal commands."""

from __future__ import annotations

import time
from dataclasses import dataclass

from osugacha_ev import ev as evmath
from osugacha_ev import alerts as alertmod
from osugacha_ev import fmt
from osugacha_ev.api import OsuGachaClient
from osugacha_ev.config import (
    BESTTIME_DAYS,
    BESTTIME_HOUR_SAMPLES,
    BESTTIME_MIN_SPAN,
    BESTTIME_ROUGH_SPAN,
    SNAPSHOT_EVERY,
    SWING_PCT,
    Settings,
)
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
        self.prices = PriceService(self.client, observer=self._observe)

    async def aclose(self) -> None:
        await self.client.aclose()
        self.store.close()

    def _observe(self, item: str, fetched, now: float) -> None:
        """feed every fresh fetch to the listing tracker."""
        self.store.observe(
            item, [(l.id, l.unit, l.qty) for l in fetched.listings], now, fetched.complete
        )

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

    async def fuel_alerts(self, now: float | None = None) -> list[tuple[int, Report]]:
        """new fuel quicksells for every subscriber. one api call, none with no subscribers."""
        subs = self.store.subscribers()
        if not subs:
            return []
        now = now if now is not None else time.time()
        fetched = await self.client.fetch(FUEL)
        self._observe(FUEL, fetched, now)
        listings = fetched.listings
        out: list[tuple[int, Report]] = []
        for user_id, pct in subs:
            for alert in alertmod.detect(listings, pct, now):
                if self.store.mark_alerted(alert.listing.id, user_id, now):
                    title, description, footer = fmt.alert_text(alert)
                    out.append((user_id, Report(title, description, footer)))
        self.store.prune_alerted(now - 7 * 86400)
        return out

    async def besttime_report(self, item_id: str = FUEL, now: float | None = None) -> Report:
        """which utc hours the stored lbin runs high or low, and when listings go."""
        now = now if now is not None else time.time()
        name = self._label(item_id)
        profile = self.store.hour_profile(item_id, now, BESTTIME_DAYS)
        if profile is None or profile.span < BESTTIME_MIN_SPAN:
            have = fmt.span_text(profile.span) if profile else "0h"
            return Report(
                fmt.lc("best time to sell"),
                fmt.lc(f"need 24h of data for {name}, have {have}. the bot keeps collecting while it runs"),
                "",
            )
        rows = [
            (h, avg, (avg / profile.overall - 1) * 100, profile.gone.get(h))
            for h, (avg, n) in sorted(profile.hours.items())
            if n >= BESTTIME_HOUR_SAMPLES
        ]
        by_price = sorted(rows, key=lambda r: r[1], reverse=True)
        sell = by_price[:3]
        buy = [r for r in by_price[::-1][:3] if r not in sell]
        busiest = [h for h, _, _, g in sorted(rows, key=lambda r: r[3] or 0, reverse=True)[:3] if profile.gone.get(h)]
        return Report(
            title=fmt.lc("best time to sell"),
            description=fmt.besttime_table(
                name, profile.span, sell, buy, busiest, profile.span < BESTTIME_ROUGH_SPAN
            ),
            footer=fmt.lc("lbin by utc hour") + fmt.SEP + fmt.lc("gone = listings that vanished"),
        )
