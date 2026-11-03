"""sqlite lbin snapshots for percent change history."""

from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path

WINDOW = 6 * 3600
MIN_AGE = 60


@dataclass(frozen=True)
class Change:
    pct: float
    age: float

    @property
    def label(self) -> str:
        return age_label(self.age)


def age_label(age: float) -> str:
    hours = round(age / 3600)
    if hours >= 1:
        return f"{hours}h"
    return f"{max(1, round(age / 60))}m"


class SnapshotStore:
    def __init__(self, path: Path | str):
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(path))
        self._db.execute(
            "create table if not exists snapshots "
            "(ts integer not null, item text not null, lbin real not null)"
        )
        self._db.execute("create index if not exists snap_item_ts on snapshots (item, ts)")
        self._db.commit()

    def close(self) -> None:
        self._db.close()

    def last_snapshot_ts(self) -> float | None:
        row = self._db.execute("select max(ts) from snapshots").fetchone()
        return row[0]

    def add(self, prices: dict[str, float | None], ts: float | None = None) -> int:
        ts = int(ts if ts is not None else time.time())
        rows = [(ts, item, lbin) for item, lbin in prices.items() if lbin is not None]
        self._db.executemany("insert into snapshots values (?, ?, ?)", rows)
        self._db.commit()
        return len(rows)

    def change(self, item: str, current: float | None, now: float | None = None) -> Change | None:
        """percent change vs 6h ago, else vs the oldest snapshot we have."""
        if current is None:
            return None
        now = now if now is not None else time.time()
        target = now - WINDOW
        row = self._db.execute(
            "select ts, lbin from snapshots where item = ? and ts <= ? order by ts desc limit 1",
            (item, target),
        ).fetchone()
        if row is None:
            row = self._db.execute(
                "select ts, lbin from snapshots where item = ? and ts <= ? order by ts asc limit 1",
                (item, now - MIN_AGE),
            ).fetchone()
        if row is None or row[1] <= 0:
            return None
        ts, old = row
        return Change(pct=(current - old) / old * 100, age=now - ts)
