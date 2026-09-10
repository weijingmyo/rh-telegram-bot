"""Telegram alert delivery."""

from __future__ import annotations

import asyncio
from typing import Iterable

import structlog
from aiogram import Bot
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramAPIError, TelegramRetryAfter

from src.storage import Database

log = structlog.get_logger(__name__)


class AlertSender:
    def __init__(
        self,
        bot: Bot | None,
        db: Database,
        *,
        extra_chat_ids: Iterable[int] | None = None,
    ) -> None:
        self.bot = bot
        self.db = db
        self.extra_chat_ids = list(extra_chat_ids or [])

    async def resolve_chat_ids(self) -> list[int]:
        subs = await self.db.list_active_subscribers()
        merged = set(subs) | set(self.extra_chat_ids)
        return sorted(merged)

    async def send_html(self, text: str) -> int:
        """Send to all subscribers; returns success count."""
        if self.bot is None:
            log.warning("alerts.no_bot", msg="Telegram bot not configured; alert dropped")
            log.info("alerts.preview", text=text[:500])
            return 0
        chat_ids = await self.resolve_chat_ids()
        if not chat_ids:
            log.warning(
                "alerts.no_subscribers",
                msg="No chat ids; use /start or TELEGRAM_CHAT_IDS",
            )
            return 0
        ok = 0
        for chat_id in chat_ids:
            try:
                await self.bot.send_message(
                    chat_id=chat_id,
                    text=text,
                    parse_mode=ParseMode.HTML,
                    disable_web_page_preview=False,
                )
                ok += 1
                await asyncio.sleep(0.05)
            except TelegramRetryAfter as exc:
                log.warning("alerts.retry_after", seconds=exc.retry_after, chat_id=chat_id)
                await asyncio.sleep(exc.retry_after + 0.5)
                try:
                    await self.bot.send_message(
                        chat_id=chat_id,
                        text=text,
                        parse_mode=ParseMode.HTML,
                    )
                    ok += 1
                except TelegramAPIError as e2:
                    log.warning("alerts.send_failed", chat_id=chat_id, error=str(e2))
            except TelegramAPIError as exc:
                log.warning("alerts.send_failed", chat_id=chat_id, error=str(exc))
        return ok
