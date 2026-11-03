"""settings. secrets come from .env only."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent

API_BASE = "https://osugacha.com/api/"
RUNS_PER_FUEL = 6
SELL_FEE = 0.02
CACHE_TTL = 300
SNAPSHOT_EVERY = 900
PAGE_LIMIT = 100
MAX_PAGES = 8
PINK = 0xFF69B4


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
