"""shared logic for the bot and the terminal commands."""

from __future__ import annotations

import time
from dataclasses import dataclass

from osugacha_ev import ev as evmath
from osugacha_ev import alerts as alertmod
from osugacha_ev import bp as bpmod
from osugacha_ev import upgrades
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

    async def _spare_mods(self) -> list[bpmod.Mod]:
        """mods you own that are not on any card."""
        found: list[bpmod.Mod] = []
        offset = 0
        for _ in range(20):
            page = await self.client.get("mods", {"equipped": "no", "limit": 100, "offset": offset})
            rows = page.get("items", [])
            found += [bpmod.Mod.from_api(m) for m in rows if m.get("status") == "available"]
            offset += len(rows)
            if not rows or offset >= page.get("total", 0):
                break
        return found

    async def _spare_copy_value(self, card: dict) -> float:
        """market value of your cheapest spare copy of a card's player."""
        page = await self.client.get("cards", {"playerId": card["player"]["id"], "limit": 100})
        values = [
            float(c.get("value", 0))
            for c in page.get("items", [])
            if c["id"] != card["id"] and not c.get("locked") and c.get("status") == "available"
        ]
        return min(values) if values else 0.0

    async def bp_report(self, count: int = 8) -> Report:
        """the cheapest battle power upgrades for your team, from your own account."""
        get = self.client.get
        squad = (await get("team")).get("squad", [])
        if not squad:
            return Report(fmt.lc("battle power"), fmt.lc("no team set on the site yet"), "")
        wallet = float((await get("wallet")).get("balance", 0))
        inventory = {i["id"]: i["qty"] for i in (await get("items")).get("items", [])}
        account_level = int((await get("account/level")).get("level", 1))
        details = [await get(f"cards/{c['id']}") for c in squad]
        cards = [(c["player"]["username"], bpmod.Card.from_api(c), c, d) for c, d in zip(squad, details)]

        wanted = {f"replay_{t}" for t in upgrades.REPLAY_XP}
        for _, card, _, _ in cards:
            if card.ascension < bpmod.MAX_ASC:
                wanted.update(upgrades.ascension_cost(card.cls, card.ascension + 1)[0])
        prices = (await self.prices.get(sorted(wanted))).lbins

        options: list[upgrades.Upgrade] = []
        for name, card, raw, detail in cards:
            cap = bpmod.level_cap(card.ascension)
            if card.level < cap:
                options.append(upgrades.level_option(name, card, raw.get("xp", 0), cap, prices, inventory, wallet))
            options.append(upgrades.ascend_option(name, card, 0, prices, inventory, wallet, account_level, False))
            options.append(upgrades.ascend_option(name, card, 0, prices, inventory, wallet, account_level, True))
            if detail.get("dupes", 0) > 0 and card.eidolon < 6:
                value = await self._spare_copy_value(raw)
                options.append(upgrades.eidolon_option(name, card, detail["dupes"], value))
        options = [o for o in options if o]
        options += upgrades.mod_swaps([(n, c) for n, c, _, _ in cards], await self._spare_mods())
        top = upgrades.rank(options)[:count]
        team = [(n, c.cls, c.rarity, bpmod.battle_power(c)) for n, c, _, _ in cards]
        return Report(
            title=fmt.lc("best bp upgrades"),
            description=fmt.bp_table(team, top, wallet),
            footer=fmt.lc("cost = lbin value of what you spend"),
        )
