"""python -m osugacha_ev [bot|ev|prices]"""

from __future__ import annotations

import asyncio
import sys

from osugacha_ev.config import load_settings


async def _print(which: str) -> None:
    from osugacha_ev.app import App

    app = App(load_settings(need_discord=False))
    try:
        report = await {"ev": app.ev_report, "prices": app.prices_report, "bp": app.bp_report, "besttime": app.besttime_report}[which]()
    finally:
        await app.aclose()
    print(report.title)
    print(report.description)
    print(report.footer)


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    which = sys.argv[1] if len(sys.argv) > 1 else "bot"
    if which in ("ev", "prices", "bp", "besttime"):
        asyncio.run(_print(which))
    elif which == "bot":
        from osugacha_ev.bot import run

        run(load_settings())
    else:
        raise SystemExit("usage: python -m osugacha_ev [bot|ev|prices|bp|besttime]")


if __name__ == "__main__":
    main()
