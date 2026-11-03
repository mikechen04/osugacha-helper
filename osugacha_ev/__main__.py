"""python -m osugacha_ev [bot|ev|prices]"""

from __future__ import annotations

import asyncio
import sys

from osugacha_ev.config import load_settings


async def _print(which: str) -> None:
    from osugacha_ev.app import App

    app = App(load_settings(need_discord=False))
    try:
        report = await (app.ev_report() if which == "ev" else app.prices_report())
    finally:
        await app.aclose()
    print(report.title)
    print(report.description)
    print(report.footer)


def main() -> None:
    which = sys.argv[1] if len(sys.argv) > 1 else "bot"
    if which in ("ev", "prices"):
        asyncio.run(_print(which))
    elif which == "bot":
        from osugacha_ev.bot import run

        run(load_settings())
    else:
        raise SystemExit("usage: python -m osugacha_ev [bot|ev|prices]")


if __name__ == "__main__":
    main()
