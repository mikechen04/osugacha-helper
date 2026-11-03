"""drop tables from drops.yaml (the api does not expose them to api keys)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass(frozen=True)
class ItemDrop:
    item: str
    low: float
    high: float

    @property
    def avg(self) -> float:
        return (self.low + self.high) / 2


@dataclass(frozen=True)
class DiffDrops:
    map: str
    diff: str
    stars_low: float
    stars_high: float
    items: tuple[ItemDrop, ...] = ()
    estimated: bool = False
    short: str = ""

    @property
    def label(self) -> str:
        return self.short or self.map

    @property
    def stars_avg(self) -> float:
        return (self.stars_low + self.stars_high) / 2


@dataclass(frozen=True)
class DropTable:
    names: dict[str, str]
    entries: list[DiffDrops] = field(default_factory=list)

    @property
    def item_ids(self) -> list[str]:
        ids = list(self.names)
        for entry in self.entries:
            for drop in entry.items:
                if drop.item not in ids:
                    ids.append(drop.item)
        return ids


def _span(value, where: str) -> tuple[float, float]:
    if isinstance(value, (int, float)):
        return float(value), float(value)
    if isinstance(value, (list, tuple)) and len(value) == 2:
        low, high = float(value[0]), float(value[1])
        if low > high:
            raise ValueError(f"{where}: min is above max")
        return low, high
    raise ValueError(f"{where}: use a number or [min, max]")


def load_drops(path: Path | str) -> DropTable:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    names = {str(k): str(v).lower() for k, v in (data.get("items") or {}).items()}
    entries: list[DiffDrops] = []
    for raw in data.get("maps") or []:
        where = f"{raw.get('map')} {raw.get('diff')}"
        s_low, s_high = _span(raw.get("stars", 0), where + " stars")
        items = tuple(
            ItemDrop(str(item), *_span(span, f"{where} {item}"))
            for item, span in (raw.get("items") or {}).items()
        )
        entries.append(
            DiffDrops(
                map=str(raw["map"]).lower(),
                diff=str(raw["diff"]).lower(),
                stars_low=s_low,
                stars_high=s_high,
                items=items,
                estimated=bool(raw.get("estimated", False)),
                short=str(raw.get("short", "")).lower(),
            )
        )
    return DropTable(names=names, entries=entries)
