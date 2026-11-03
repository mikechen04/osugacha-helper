"""shared logic for the bot and the terminal commands."""

from __future__ import annotations

import time
from dataclasses import dataclass
from urllib.parse import quote

from osugacha_ev import ev as evmath
from osugacha_ev import alerts as alertmod
from osugacha_ev import bp as bpmod
from osugacha_ev import upgrades
from osugacha_ev import fmt
from osugacha_ev.api import ApiError, OsuGachaClient
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

    async def _profile(self, username: str) -> dict | None:
        try:
            return await self.client.get(f"users/{quote(username, safe='')}/profile")
        except ApiError as err:
            if err.status == 404:
                return None
            raise

    async def find_user(self, username: str) -> str | None:
        """the site's spelling of a username, or None if there is no such player."""
        try:
            data = await self.client.get(f"users/{quote(username.strip(), safe='')}")
        except ApiError as err:
            if err.status == 404:
                return None
            raise
        return (data.get("user") or {}).get("username")

    async def _spare_mods(self, username: str) -> list[bpmod.Mod]:
        """mods a player owns that are not on a card (the public list holds only those)."""
        found: list[bpmod.Mod] = []
        offset = 0
        for _ in range(20):
            page = await self.client.get(
                f"users/{quote(username, safe='')}/mods", {"limit": 100, "offset": offset}
            )
            rows = page.get("items", [])
            found += [bpmod.Mod.from_api(m) for m in rows if not m.get("equippedCardId")]
            offset += len(rows)
            if not rows or offset >= page.get("total", 0):
                break
        return found

    async def _copy_price(self, card: dict) -> float | None:
        """cheapest market listing of a spare copy that can be fed into this card.

        a signature card only takes a copy of the same signature, and a normal
        card only takes normal copies, so the two are priced apart.
        """
        player = card["player"]
        sig_id = (card.get("sig") or {}).get("id")
        for page_no in range(5):
            page = await self.client.get(
                "market/listings",
                {
                    "kind": "card",
                    "q": player["username"],
                    "sort": "price_asc",
                    "limit": 100,
                    "offset": page_no * 100,
                },
            )
            rows = page.get("items", [])
            for row in rows:  # cheapest first, so the first match is the answer
                listed = row.get("card") or {}
                if (
                    row.get("kind") == "card"
                    and row.get("mode") == "bin"
                    and listed.get("player", {}).get("id") == player["id"]
                    and (listed.get("sig") or {}).get("id") == sig_id
                ):
                    return float(row["price"])
            if len(rows) < 100:
                break
        return None

    async def bp_report(self, username: str, count: int = 8) -> Report:
        """the cheapest battle power upgrades for a player's team, from public data only."""
        profile = await self._profile(username)
        if profile is None:
            return Report(fmt.lc("battle power"), fmt.lc(f"no player named {username}"), "")
        name = (profile.get("user") or {}).get("username") or username
        squad = profile.get("squad") or []
        if not squad:
            return Report(fmt.lc("battle power"), fmt.lc(f"{name} has no team set"), "")
        stats = profile.get("stats") or {}
        account_level = int((stats.get("level") or {}).get("level", 1))
        cards = [(c["player"]["username"], bpmod.Card.from_api(c), c) for c in squad]

        wanted = {f"replay_{t}" for t in upgrades.REPLAY_XP}
        for _, card, _ in cards:
            if card.ascension < bpmod.MAX_ASC:
                wanted.update(upgrades.ascension_cost(card.cls, card.ascension + 1)[0])
        prices = (await self.prices.get(sorted(wanted))).lbins

        options: list[upgrades.Upgrade | None] = []
        for card_name, card, raw in cards:
            cap = bpmod.level_cap(card.ascension)
            if card.level < cap:
                options.append(upgrades.level_option(card_name, card, raw.get("xp", 0), cap, prices, {}, 0))
            options.append(upgrades.ascend_option(card_name, card, 0, prices, {}, 0, account_level, False))
            options.append(upgrades.ascend_option(card_name, card, 0, prices, {}, 0, account_level, True))
            if card.eidolon < 6:
                copy = await self._copy_price(raw)
                if copy is not None:
                    options.append(upgrades.eidolon_option(card_name, card, 1, copy))
        found = [o for o in options if o]
        found += upgrades.mod_swaps([(n, c) for n, c, _ in cards], await self._spare_mods(name))
        top = upgrades.rank(found)[:count]
        team = [(n, c.cls, c.rarity, bpmod.battle_power(c)) for n, c, _ in cards]
        power = (stats.get("team") or {}).get("power") or sum(t[3] for t in team)
        return Report(
            title=fmt.lc(f"best bp upgrades for {name}"),
            description=fmt.bp_table(team, top, power, account_level),
            footer=fmt.lc("cost = lbin value of what you spend"),
        )
