"""thin async client for the osugacha api. read-only."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import httpx

from osugacha_ev.config import API_BASE, MAX_PAGES, PAGE_LIMIT


class ApiError(RuntimeError):
    def __init__(self, status: int, payload: Any):
        self.status = status
        self.payload = payload
        super().__init__(f"api {status}")


@dataclass(frozen=True)
class Listing:
    id: str
    unit: float  # per unit buy it now price
    qty: int
    price: int  # total for the listing
    created_at: float  # unix seconds, 0 if unknown


@dataclass(frozen=True)
class Fetch:
    listings: list[Listing]
    complete: bool  # False if the page cap cut the book short


@dataclass(frozen=True)
class Quote:
    lbin: float
    listings: int
    gap: float | None  # second lowest listing vs the lowest, 0.1 = 10% higher


class OsuGachaClient:
    def __init__(
        self,
        api_key: str,
        *,
        timeout: float = 20.0,
        transport: httpx.AsyncBaseTransport | None = None,
        sleep=asyncio.sleep,
    ):
        if not api_key:
            raise ValueError("api key is missing")
        self._sleep = sleep
        self._client = httpx.AsyncClient(
            base_url=API_BASE,
            timeout=timeout,
            transport=transport,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Accept": "application/json",
                "User-Agent": "osugacha-ev-bot/1.0",
            },
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        last: ApiError | None = None
        for attempt in range(4):
            response = await self._client.get(path.lstrip("/"), params=params)
            try:
                payload = response.json()
            except ValueError:
                payload = {"text": response.text[:200]}
            if response.status_code != 429:
                if response.status_code >= 400:
                    raise ApiError(response.status_code, payload)
                return payload
            last = ApiError(429, payload)
            header = response.headers.get("retry-after", "")
            try:
                wait = float(header)
            except ValueError:
                wait = 5.0 * (attempt + 1)
            await self._sleep(min(wait, 60.0))
        assert last is not None
        raise last

    async def fetch(self, item_id: str) -> Fetch:
        """every buy it now listing for an item or mod id, cheapest unit first.

        item_id is a market item id such as "fuel", or "mod:ht:4" for 4 star
        half time mods.
        """
        params, parse = listing_query(item_id)
        found: list[Listing] = []
        offset = 0
        complete = False
        for _ in range(MAX_PAGES):
            page = await self.get(
                "market/listings",
                {**params, "sort": "price_asc", "limit": PAGE_LIMIT, "offset": offset},
            )
            rows = page.get("items", [])
            for row in rows:
                if row.get("mode") != "bin":
                    continue
                listing = parse(row)
                if listing is not None:
                    found.append(listing)
            offset += len(rows)
            if not rows or offset >= page.get("total", 0):
                complete = True
                break
        return Fetch(sorted(found, key=lambda l: l.unit), complete)

    async def card_floor(self, rarity: str, count: int = 20) -> tuple[list[Listing], dict[str, dict]]:
        """the cheapest buy it now card listings of one rarity, plus each card's details by listing id."""
        page = await self.get(
            "market/listings",
            {"kind": "card", "rarity": rarity, "sort": "price_asc", "limit": count},
        )
        listings: list[Listing] = []
        cards: dict[str, dict] = {}
        for row in page.get("items", []):
            card = row.get("card") or {}
            if row.get("mode") != "bin" or card.get("rarity") != rarity:
                continue
            lid = str(row.get("id", ""))
            listings.append(Listing(lid, float(row["price"]), 1, row["price"], _created(row)))
            cards[lid] = card
        return sorted(listings, key=lambda l: l.unit), cards

    async def bin_listings(self, item_id: str) -> list[Listing]:
        return (await self.fetch(item_id)).listings

    async def quote(self, item_id: str) -> Quote | None:
        """lowest per unit buy it now price plus how deep the listings are."""
        return quote_of((await self.fetch(item_id)).listings)

    async def lbin(self, item_id: str) -> float | None:
        quote = await self.quote(item_id)
        return quote.lbin if quote else None


def quote_of(listings: list[Listing]) -> Quote | None:
    units = sorted(l.unit for l in listings)
    if not units:
        return None
    gap = units[1] / units[0] - 1 if len(units) > 1 and units[0] > 0 else None
    return Quote(lbin=units[0], listings=len(units), gap=gap)


def _created(row: dict) -> float:
    try:
        return datetime.fromisoformat(row["createdAt"]).timestamp()
    except (KeyError, TypeError, ValueError):
        return 0.0


def listing_query(item_id: str) -> tuple[dict[str, Any], Callable[[dict], Listing | None]]:
    """(query params, row -> Listing or None) for an item or mod id."""
    if item_id.startswith("mod:"):
        _, mod_type, rarity = item_id.split(":")
        params = {"kind": "mod", "modType": mod_type, "modRarity": int(rarity)}

        def parse_mod(row: dict) -> Listing | None:
            mod = row.get("mod") or {}
            if mod.get("type") != mod_type or mod.get("rarity") != int(rarity):
                return None
            return Listing(str(row.get("id", "")), float(row["price"]), 1, row["price"], _created(row))

        return params, parse_mod

    params = {"kind": "item", "itemId": item_id}

    def parse_item(row: dict) -> Listing | None:
        item = row.get("item") or {}
        qty = item.get("qty") or 0
        if item.get("id") != item_id or qty <= 0:
            return None
        return Listing(str(row.get("id", "")), row["price"] / qty, qty, row["price"], _created(row))

    return params, parse_item
