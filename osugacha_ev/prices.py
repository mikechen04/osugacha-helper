"""lbin lookups with a short cache."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass

from osugacha_ev.api import OsuGachaClient
from osugacha_ev.config import CACHE_TTL


@dataclass(frozen=True)
class PriceBook:
    lbins: dict[str, float | None]
    fetched_at: float


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
        self._cache: dict[str, tuple[float | None, float]] = {}
        self._lock = asyncio.Lock()

    async def get(self, item_ids: Iterable[str], *, force: bool = False) -> PriceBook:
        ids = list(dict.fromkeys(item_ids))
        async with self._lock:
            for item_id in ids:
                cached = self._cache.get(item_id)
                if force or cached is None or self._clock() - cached[1] >= self._ttl:
                    lbin = await self._client.lbin(item_id)
                    self._cache[item_id] = (lbin, self._clock())
        return PriceBook(
            lbins={i: self._cache[i][0] for i in ids},
            fetched_at=min(self._cache[i][1] for i in ids) if ids else self._clock(),
        )
