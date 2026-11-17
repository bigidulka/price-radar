"""Command line entry point.

    price-radar demo-site docs/          # build the static demo dashboard (GitHub Pages)
    price-radar serve --demo             # dashboard on http://127.0.0.1:8000 with synthetic data
    price-radar serve                    # dashboard over the real database
    price-radar bot                      # Telegram bot (TELEGRAM_BOT_TOKEN, PRICE_RADAR_ADMINS)
    price-radar refresh [--apply]        # one polling cycle, prints a digest
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
from pathlib import Path

from .providers import OzonProvider, WildberriesProvider
from .service import Radar
from .storage import Store


def _radar(db: str) -> Radar:
    proxy = os.getenv("PRICE_RADAR_PROXY") or None
    return Radar(Store(db), {"wb": WildberriesProvider(proxy=proxy), "ozon": OzonProvider(os.getenv("OZON_CDP"))})


def _demo_radar() -> Radar:
    from . import demo

    store = Store(":memory:")
    provider = asyncio.run(demo.simulate(store))
    return Radar(store, {"demo": provider})


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="price-radar")
    ap.add_argument("--db", default=os.getenv("PRICE_RADAR_DB", "price_radar.sqlite"))
    sub = ap.add_subparsers(dest="cmd", required=True)
    site = sub.add_parser("demo-site", help="render the static demo dashboard")
    site.add_argument("out", type=Path)
    serve = sub.add_parser("serve", help="run the web dashboard")
    serve.add_argument("--demo", action="store_true")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    sub.add_parser("bot", help="run the Telegram bot")
    ref = sub.add_parser("refresh", help="poll all tracked listings once")
    ref.add_argument("--apply", action="store_true")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    if args.cmd == "demo-site":
        from .view import render, snapshot

        radar = _demo_radar()
        args.out.mkdir(parents=True, exist_ok=True)
        (args.out / "index.html").write_text(render(snapshot(radar.store), demo=True), encoding="utf-8")
        from .export import workbook_bytes

        (args.out / "price-radar-demo.xlsx").write_bytes(workbook_bytes(radar.store))
        print(f"written {args.out / 'index.html'}")
    elif args.cmd == "serve":
        import uvicorn

        from .web import create_app

        radar = _demo_radar() if args.demo else _radar(args.db)
        uvicorn.run(create_app(radar, demo=args.demo), host=args.host, port=args.port)
    elif args.cmd == "bot":
        from .bot import run

        token = os.environ.get("TELEGRAM_BOT_TOKEN")
        if not token:
            raise SystemExit("TELEGRAM_BOT_TOKEN is not set")
        admins = {int(x) for x in os.getenv("PRICE_RADAR_ADMINS", "").split(",") if x.strip()}
        if not admins:
            raise SystemExit("PRICE_RADAR_ADMINS is empty: the bot changes prices, restrict it to your user id")
        asyncio.run(run(token, _radar(args.db), admins, int(os.getenv("PRICE_RADAR_INTERVAL", "30"))))
    elif args.cmd == "refresh":
        from .bot import digest

        radar = _radar(args.db)
        print(digest(asyncio.run(radar.refresh(apply=args.apply)), radar.store))


if __name__ == "__main__":
    main()
