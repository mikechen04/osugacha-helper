"""lbin lookups with a short cache."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass

from osugacha_ev.api import OsuGachaClient, Quote
from osugacha_ev.config import CACHE_TTL, THIN_GAP, THIN_LISTINGS


@dataclass(frozen=True)
class PriceBook:
    quotes: dict[str, Quote | None]
    fetched_at: float

    @property
    def lbins(self) -> dict[str, float | None]:
        return {item: q.lbin if q else None for item, q in self.quotes.items()}

    def thin(self) -> set[str]:
        return {item for item, q in self.quotes.items() if is_thin(q)}


def is_thin(quote: Quote | None) -> bool:
    """few listings, or the lowest one sits far under the rest (likely a one off)."""
    if quote is None:
        return False
    if quote.listings < THIN_LISTINGS:
        return True
    return quote.gap is not None and quote.gap > THIN_GAP


class PriceService:
    def __init__(
        self,
        client: OsuGachaClient,
        *,
        ttl: float = CACHE_TTL,
        clock: Callable[[], float] = time.time,
    ):
        self._client = client
        self._ttl = ttl
        self._clock = clock
        self._cache: dict[str, tuple[Quote | None, float]] = {}
        self._lock = asyncio.Lock()

    async def get(self, item_ids: Iterable[str], *, force: bool = False) -> PriceBook:
        ids = list(dict.fromkeys(item_ids))
        async with self._lock:
            for item_id in ids:
                cached = self._cache.get(item_id)
                if force or cached is None or self._clock() - cached[1] >= self._ttl:
                    quote = await self._client.quote(item_id)
                    self._cache[item_id] = (quote, self._clock())
        return PriceBook(
            quotes={i: self._cache[i][0] for i in ids},
            fetched_at=min(self._cache[i][1] for i in ids) if ids else self._clock(),
        )
