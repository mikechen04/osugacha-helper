"""sqlite lbin snapshots for percent change history."""

from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path

from osugacha_ev.config import OBS_GAP

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
        self._db.execute(
            "create table if not exists alert_subs "
            "(user_id integer primary key, pct real not null)"
        )
        self._db.execute(
            "create table if not exists open_listings (item text not null, listing_id text not null, "
            "unit real not null, qty integer not null, primary key (item, listing_id))"
        )
        self._db.execute(
            "create table if not exists gone (item text not null, ts integer not null, "
            "unit real not null, qty integer not null)"
        )
        self._db.execute(
            "create table if not exists obs (item text primary key, ts integer not null, "
            "first_ts integer not null)"
        )
        self._db.execute(
            "create table if not exists links (discord_id integer primary key, username text not null)"
        )
        self._db.execute(
            "create table if not exists alerted "
            "(listing_id text not null, user_id integer not null, ts integer not null, "
            "primary key (listing_id, user_id))"
        )
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

    # discord user -> osu gacha username

    def set_link(self, discord_id: int, username: str | None) -> None:
        """link a discord user to an osu gacha username, or unlink with None."""
        if username is None:
            self._db.execute("delete from links where discord_id = ?", (discord_id,))
        else:
            self._db.execute(
                "insert into links values (?, ?) "
                "on conflict(discord_id) do update set username = excluded.username",
                (discord_id, username),
            )
        self._db.commit()

    def get_link(self, discord_id: int) -> str | None:
        row = self._db.execute("select username from links where discord_id = ?", (discord_id,)).fetchone()
        return row[0] if row else None

    # fuel quicksell alerts

    def set_alert(self, user_id: int, pct: float | None) -> None:
        """subscribe a user at pct percent, or unsubscribe with None."""
        if pct is None:
            self._db.execute("delete from alert_subs where user_id = ?", (user_id,))
        else:
            self._db.execute(
                "insert into alert_subs values (?, ?) "
                "on conflict(user_id) do update set pct = excluded.pct",
                (user_id, pct),
            )
        self._db.commit()

    def get_alert(self, user_id: int) -> float | None:
        row = self._db.execute("select pct from alert_subs where user_id = ?", (user_id,)).fetchone()
        return row[0] if row else None

    def subscribers(self) -> list[tuple[int, float]]:
        return list(self._db.execute("select user_id, pct from alert_subs"))

    def mark_alerted(self, listing_id: str, user_id: int, ts: float) -> bool:
        """record that a user was told about a listing. False if they already were."""
        cur = self._db.execute(
            "insert or ignore into alerted values (?, ?, ?)", (listing_id, user_id, int(ts))
        )
        self._db.commit()
        return cur.rowcount == 1

    def prune_alerted(self, before: float) -> None:
        self._db.execute("delete from alerted where ts < ?", (int(before),))
        self._db.commit()

    # listing tracker and hour of day profile

    def observe(
        self,
        item: str,
        listings: list[tuple[str, float, int]],
        ts: float,
        complete: bool,
        max_gap: float = OBS_GAP,
    ) -> int:
        """record the current buy it now listings (id, unit, qty) for an item.

        a listing that was open at the last look and is missing now is counted as
        gone (sold, cancelled or expired), but only when the last look was close
        enough in time and both looks saw the whole book. returns how many went.
        """
        ts = int(ts)
        row = self._db.execute("select ts from obs where item = ?", (item,)).fetchone()
        last = row[0] if row else None
        current = {lid: (unit, qty) for lid, unit, qty in listings}
        gone = []
        if complete:
            trusted = last is not None and ts - last <= max_gap
            for lid, unit, qty in self._db.execute(
                "select listing_id, unit, qty from open_listings where item = ?", (item,)
            ).fetchall():
                if lid not in current:
                    if trusted:
                        gone.append((item, ts, unit, qty))
                    self._db.execute(
                        "delete from open_listings where item = ? and listing_id = ?", (item, lid)
                    )
            self._db.execute(
                "insert into obs values (?, ?, ?) on conflict(item) do update set ts = excluded.ts",
                (item, ts, ts),
            )
        self._db.executemany(
            "insert or ignore into open_listings values (?, ?, ?, ?)",
            [(item, lid, unit, qty) for lid, (unit, qty) in current.items()],
        )
        self._db.executemany("insert into gone values (?, ?, ?, ?)", gone)
        self._db.commit()
        return len(gone)

    def hour_profile(self, item: str, now: float | None = None, days: int = 14) -> "HourProfile | None":
        """average stored lbin by utc hour, plus units gone per day by hour."""
        now = now if now is not None else time.time()
        since = now - days * 86400
        count, first, last, overall = self._db.execute(
            "select count(*), min(ts), max(ts), avg(lbin) from snapshots where item = ? and ts >= ?",
            (item, since),
        ).fetchone()
        if not count:
            return None
        hours = {
            h: (avg, n)
            for h, avg, n in self._db.execute(
                "select cast(strftime('%H', ts, 'unixepoch') as integer), avg(lbin), count(*) "
                "from snapshots where item = ? and ts >= ? group by 1",
                (item, since),
            )
        }
        obs = self._db.execute("select first_ts from obs where item = ?", (item,)).fetchone()
        gone: dict[int, float] = {}
        if obs:
            watched_days = max((now - obs[0]) / 86400, 1.0)
            for h, units in self._db.execute(
                "select cast(strftime('%H', ts, 'unixepoch') as integer), sum(qty) "
                "from gone where item = ? and ts >= ? group by 1",
                (item, since),
            ):
                gone[h] = units / watched_days
        return HourProfile(span=last - first, overall=overall, hours=hours, gone=gone)


@dataclass(frozen=True)
class HourProfile:
    span: float  # seconds between the first and last snapshot used
    overall: float  # mean stored lbin
    hours: dict[int, tuple[float, int]]  # utc hour -> (mean lbin, samples)
    gone: dict[int, float]  # utc hour -> units gone per day
