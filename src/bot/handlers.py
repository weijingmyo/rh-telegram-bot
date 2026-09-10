"""Telegram command handlers."""

from __future__ import annotations

from aiogram import Dispatcher, F, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

from src.alerts import format_dev_lookup
from src.blacklist import BlacklistService
from src.config import Settings
from src.gmgn import GmgnClient
from src.scanner import TokenScanner
from src.storage import Database


def build_router(
    *,
    settings: Settings,
    db: Database,
    scanner: TokenScanner,
    blacklist: BlacklistService,
    gmgn: GmgnClient,
) -> Router:
    router = Router(name="commands")

    @router.message(Command("start"))
    async def cmd_start(message: Message) -> None:
        if message.chat:
            await db.add_subscriber(message.chat.id)
        text = (
            "已订阅 Robinhood 新币预警。"
            + chr(10)
            + "命令：/stop /status /blacklist /dev <address>"
            + chr(10)
            + "标签：[推特大V] [高ATH Dev]"
        )
        await message.answer(text)
        if settings.auto_start_scanner and not scanner.stats.running:
            await scanner.start()

    @router.message(Command("stop"))
    async def cmd_stop(message: Message) -> None:
        if message.chat:
            await db.remove_subscriber(message.chat.id)
        await scanner.stop()
        await message.answer("已取消订阅，并停止扫描。发送 /start 可重新开启。")

    @router.message(Command("status"))
    async def cmd_status(message: Message) -> None:
        st = scanner.status_dict()
        db_stats = await db.stats()
        lines = [
            "<b>Bot Status</b>",
            f"扫描中：{'是' if st['running'] else '否'}",
            f"链：{', '.join(st['chains'])}",
            f"周期：{st['cycles']} · 新币：{st['tokens_seen']} · 告警发送：{st['alerts_sent']}",
            f"上次周期：{st['last_cycle_at'] or '-'}",
            (
                f"DB seen={db_stats['seen_tokens']} alerts={db_stats['alert_pairs']} "
                f"blacklist={db_stats['blacklisted']} subs={db_stats['subscribers']}"
            ),
            f"Twitter：{'已配置' if st['twitter_configured'] else '未配置(跳过)'}",
            (
                f"阈值：粉丝>{settings.follower_threshold} · "
                f"ATH>={settings.ath_mc_threshold:.0f} · "
                f"惯犯上限={settings.blacklist_alert_limit}"
            ),
        ]
        if st["last_error"]:
            lines.append(f"最近错误：{st['last_error'][:200]}")
        await message.answer(chr(10).join(lines), parse_mode="HTML")

    @router.message(Command("blacklist"))
    async def cmd_blacklist(message: Message) -> None:
        items = await blacklist.list_all(limit=30)
        if not items:
            await message.answer("黑名单为空。")
            return
        lines = ["<b>惯犯黑名单</b>（累计告警达上限）"]
        for it in items:
            lines.append(
                f"• [{it.entity_type}] <code>{it.entity_key}</code> count={it.alert_count}"
            )
        await message.answer(chr(10).join(lines), parse_mode="HTML")

    @router.message(Command("dev"))
    async def cmd_dev(message: Message, command: CommandObject) -> None:
        addr = (command.args or "").strip()
        if not addr:
            await message.answer("用法：/dev <wallet_address>")
            return
        await message.answer(f"查询 Dev <code>{addr}</code> …", parse_mode="HTML")
        history = await gmgn.fetch_full_launch_history(addr)
        text = format_dev_lookup(None, history, addr)
        entity = await db.get_entity("dev", addr)
        text += (
            chr(10)
            + chr(10)
            + f"惯犯状态：{'已拉黑' if entity.blacklisted else '正常'} "
            + f"({entity.alert_count}/{settings.blacklist_alert_limit})"
        )
        await message.answer(text, parse_mode="HTML")

    @router.message(F.text & ~F.text.startswith("/"))
    async def fallback(message: Message) -> None:
        await message.answer("支持命令：/start /stop /status /blacklist /dev <address>")

    return router


def setup_dispatcher(
    dp: Dispatcher,
    *,
    settings: Settings,
    db: Database,
    scanner: TokenScanner,
    blacklist: BlacklistService,
    gmgn: GmgnClient,
) -> None:
    dp.include_router(
        build_router(
            settings=settings,
            db=db,
            scanner=scanner,
            blacklist=blacklist,
            gmgn=gmgn,
        )
    )
