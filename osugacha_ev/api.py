"""thin async client for the osugacha api. read-only."""

from __future__ import annotations

import asyncio
from typing import Any

import httpx

from osugacha_ev.config import API_BASE, MAX_PAGES, PAGE_LIMIT


class ApiError(RuntimeError):
    def __init__(self, status: int, payload: Any):
        self.status = status
        self.payload = payload
        super().__init__(f"api {status}")


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

    async def lbin(self, item_id: str) -> float | None:
        """lowest per unit buy it now price, or None if unlisted.

        item_id is a market item id such as "fuel", or "mod:ht:4" for the
        cheapest 4 star half time mod.
        """
        params, unit_price = listing_query(item_id)
        best: float | None = None
        offset = 0
        for _ in range(MAX_PAGES):
            page = await self.get(
                "market/listings",
                {**params, "sort": "price_asc", "limit": PAGE_LIMIT, "offset": offset},
            )
            rows = page.get("items", [])
            for row in rows:
                if row.get("mode") != "bin":
                    continue
                unit = unit_price(row)
                if unit is not None and (best is None or unit < best):
                    best = unit
            offset += len(rows)
            if not rows or offset >= page.get("total", 0):
                break
        return best


def listing_query(item_id: str):
    """(query params, row -> unit price or None) for an item or mod id."""
    if item_id.startswith("mod:"):
        _, mod_type, rarity = item_id.split(":")
        params = {"kind": "mod", "modType": mod_type, "modRarity": int(rarity)}

        def mod_price(row):
            mod = row.get("mod") or {}
            if mod.get("type") != mod_type or mod.get("rarity") != int(rarity):
                return None
            return float(row["price"])

        return params, mod_price

    params = {"kind": "item", "itemId": item_id}

    def item_price(row):
        item = row.get("item") or {}
        qty = item.get("qty") or 0
        if item.get("id") != item_id or qty <= 0:
            return None
        return row["price"] / qty

    return params, item_price
