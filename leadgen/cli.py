"""Командная строка: поиск, подготовка карточек, веб-интерфейс, вход в Telegram."""

from __future__ import annotations

import argparse
import asyncio
import logging

from . import mockup, pipeline
from .config import load_settings
from .db import Store
from .offer import OfferGenerator
from .sources import available_sources, build_sources


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="leadgen", description=__doc__)
    parser.add_argument("--env", default=".env", help="путь к .env")
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("search", help="найти лиды по нише")
    p.add_argument("niche", help="например: «ремонт техники»")
    p.add_argument("--sources", help="через запятую; по умолчанию все настроенные")
    p.add_argument("--limit", type=int, default=30, help="сколько результатов брать на фразу")
    p.add_argument("--expand", action="store_true", help="искать ещё и по фразам из профиля ниши")
    p.add_argument("--no-prepare", action="store_true", help="только собрать, без предложений и макетов")

    p = sub.add_parser("prepare", help="подготовить предложения для лидов без них")
    p.add_argument("--no-mockups", action="store_true")

    p = sub.add_parser("serve", help="запустить веб-интерфейс")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8000)

    sub.add_parser("sources", help="показать настроенные источники")
    sub.add_parser("tg-login", help="один раз войти в Telegram (код придёт в приложение)")

    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING, format="%(levelname)s %(message)s")
    settings = load_settings(args.env)
    settings.ensure_dirs()

    if args.cmd == "sources":
        names = available_sources(settings)
        print("\n".join(names) if names else "Источники не настроены — см. .env.example")
        return

    if args.cmd == "tg-login":
        from .sources.telegram import login

        if not settings.tg_api_id or not settings.tg_api_hash:
            raise SystemExit("Заполните TG_API_ID и TG_API_HASH в .env")
        asyncio.run(login(settings.tg_api_id, settings.tg_api_hash, settings.tg_session))
        return

    if args.cmd == "serve":
        import uvicorn

        from .web.app import create_app

        uvicorn.run(create_app(settings), host=args.host, port=args.port)
        return

    store = Store(settings.db_path)
    try:
        if args.cmd == "search":
            names = args.sources.split(",") if args.sources else available_sources(settings)
            sources, errors = build_sources(settings, names)
            for e in errors:
                print(f"! {e}")
            stats = pipeline.run_search(store, sources, args.niche, limit=args.limit, expand=args.expand)
            for src in sources:
                src.close()
            print(stats.summary())
            if not args.no_prepare and stats.new_ids:
                n = pipeline.prepare_pending(store, OfferGenerator(settings), mockup.MockupBuilder(settings),
                                             ids=stats.new_ids)
                print(f"подготовлено карточек: {n}")
        elif args.cmd == "prepare":
            builder = None if args.no_mockups else mockup.MockupBuilder(settings)
            n = pipeline.prepare_pending(store, OfferGenerator(settings), builder)
            print(f"подготовлено карточек: {n}")
    finally:
        store.close()


if __name__ == "__main__":
    main()
