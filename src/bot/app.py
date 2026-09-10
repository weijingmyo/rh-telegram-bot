"""Telegram bot application wiring."""

from __future__ import annotations

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from src.bot.handlers import setup_dispatcher
from src.blacklist import BlacklistService
from src.config import Settings
from src.gmgn import GmgnClient
from src.scanner import TokenScanner
from src.storage import Database


def create_bot(settings: Settings) -> Bot | None:
    if not settings.telegram_configured:
        return None
    return Bot(
        token=settings.telegram_bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )


def create_dispatcher(
    *,
    settings: Settings,
    db: Database,
    scanner: TokenScanner,
    blacklist: BlacklistService,
    gmgn: GmgnClient,
) -> Dispatcher:
    dp = Dispatcher()
    setup_dispatcher(
        dp,
        settings=settings,
        db=db,
        scanner=scanner,
        blacklist=blacklist,
        gmgn=gmgn,
    )
    return dp
