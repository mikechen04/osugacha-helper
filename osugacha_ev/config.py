"""settings. secrets come from .env only."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent

API_BASE = "https://osugacha.com/api/"
RUNS_PER_FUEL = 6
# the stars refill gives 60 stamina, the same as one fuel
REFILL_STARS = 7900
SELL_FEE = 0.02
CACHE_TTL = 300
SNAPSHOT_EVERY = 900
PAGE_LIMIT = 100
MAX_PAGES = 8
PINK = 0xFF69B4

# low volume warnings. the api has no sales history, so thin means few
# listings or a lowest listing far under the next one, and swingy means lbin
# moved this many percent versus 6h ago (or the oldest snapshot we have).
THIN_LISTINGS = 3
THIN_GAP = 0.20
SWING_PCT = 20.0
WARN_SHARE = 0.15

# fuel quicksell alerts. a listing counts when it is at most this old, and the
# bottom this many listings are compared with the next lbin above them.
ALERT_MAX_AGE = 900
ALERT_MAX_CLUSTER = 2
ALERT_POLL = 30
# card undercut alerts: the market sells mythic and divine above legendary (restricted is not listed)
CARD_RARITIES = ("mythic", "divine")
CARD_POLL = 60
CARD_BOTTOM = 20  # how many of the cheapest listings of a rarity to look at
CARD_DEFAULT_PCT = 15

# best time to sell. listings that vanish between two looks count as gone, but
# only when the looks are close enough together to trust.
OBS_GAP = 2 * SNAPSHOT_EVERY + 60
BESTTIME_MIN_SPAN = 24 * 3600
BESTTIME_ROUGH_SPAN = 3 * 24 * 3600
BESTTIME_HOUR_SAMPLES = 4
BESTTIME_DAYS = 14


@dataclass(frozen=True)
class Settings:
    discord_token: str
    discord_app_id: int
    api_key: str
    drops_file: Path
    db_file: Path


def load_settings(*, need_discord: bool = True) -> Settings:
    load_dotenv(ROOT / ".env")
    api_key = os.getenv("OSUGACHA_API_KEY", "").strip()
    token = os.getenv("DISCORD_TOKEN", "").strip()
    app_id = os.getenv("DISCORD_APP_ID", "").strip()
    missing = [
        name
        for name, value, needed in (
            ("OSUGACHA_API_KEY", api_key, True),
            ("DISCORD_TOKEN", token, need_discord),
            ("DISCORD_APP_ID", app_id, need_discord),
        )
        if needed and not value
    ]
    if missing:
        raise SystemExit("missing in .env: " + ", ".join(missing))
    return Settings(
        discord_token=token,
        discord_app_id=int(app_id) if app_id else 0,
        api_key=api_key,
        drops_file=ROOT / "drops.yaml",
        db_file=ROOT / "data" / "lbin.db",
    )
