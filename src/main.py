"""Application entrypoint."""

from __future__ import annotations

import asyncio
import signal
from typing import Any

import structlog

from src.alerts import AlertSender
from src.blacklist import BlacklistService
from src.bot import create_bot, create_dispatcher
from src.config import get_settings
from src.gmgn import GmgnClient
from src.health import start_health_server
from src.logging_setup import setup_logging
from src.scanner import TokenScanner
from src.storage import Database
from src.twitter import build_twitter_provider

log = structlog.get_logger(__name__)


async def async_main() -> None:
    settings = get_settings()
    setup_logging(settings.log_level)

    if not settings.telegram_configured:
        log.warning("startup.telegram_missing", msg="TELEGRAM_BOT_TOKEN missing; bot will not poll")
    if not settings.twitter_configured:
        log.warning("startup.twitter_missing", msg="Twitter keys missing; tweet alerts skipped")
    if not settings.gmgn_api_key:
        log.warning(
            "startup.gmgn_key_missing",
            msg="GMGN_API_KEY missing; CLI may still work via ~/.config/gmgn/.env",
        )

    db = Database(settings.db_path)
    await db.connect()

    # Seed env chat ids as subscribers
    for cid in settings.chat_id_list:
        await db.add_subscriber(cid)

    gmgn = GmgnClient(settings)
    await gmgn.check_available()
    twitter = build_twitter_provider(settings)
    blacklist = BlacklistService(db, limit=settings.blacklist_alert_limit)

    bot = create_bot(settings)
    sender = AlertSender(bot, db, extra_chat_ids=settings.chat_id_list)
    scanner = TokenScanner(
        settings=settings,
        db=db,
        gmgn=gmgn,
        twitter=twitter,
        blacklist=blacklist,
        alerts=sender,
    )

    async def health_status() -> dict[str, Any]:
        st = scanner.status_dict()
        db_stats = await db.stats()
        return {
            "ok": True,
            "scanner": st,
            "db": db_stats,
        }

    health_runner = await start_health_server(
        settings.health_host,
        settings.health_port,
        health_status,
    )

    stop_event = asyncio.Event()

    def _ask_stop(*_: Any) -> None:
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _ask_stop)
        except NotImplementedError:
            pass

    if settings.auto_start_scanner:
        await scanner.start()

    dp = create_dispatcher(
        settings=settings,
        db=db,
        scanner=scanner,
        blacklist=blacklist,
        gmgn=gmgn,
    )

    poll_task = None
    if bot is not None:
        poll_task = asyncio.create_task(dp.start_polling(bot), name="telegram-polling")
        log.info("startup.polling")
    else:
        log.warning("startup.no_polling")

    await stop_event.wait()
    log.info("shutdown.begin")

    await scanner.stop()
    if poll_task:
        poll_task.cancel()
        try:
            await poll_task
        except asyncio.CancelledError:
            pass
    if bot is not None:
        await bot.session.close()
    await twitter.close()
    await gmgn.close()
    await health_runner.cleanup()
    await db.close()
    log.info("shutdown.done")


def main() -> None:
    try:
        asyncio.run(async_main())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
