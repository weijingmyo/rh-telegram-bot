"""Chinese HTML alert message formatter."""

from __future__ import annotations

import html
from typing import Iterable

from src.gmgn.models import CreatedToken, DevLaunchHistory, TokenInfo
from src.twitter.base import TweetMatch


def _e(text: object) -> str:
    return html.escape(str(text), quote=False)


def _fmt_usd(value: float) -> str:
    if value >= 1_000_000:
        return f"${value/1_000_000:.2f}M"
    if value >= 1_000:
        return f"${value/1_000:.2f}K"
    return f"${value:.2f}"


def _history_block(history: DevLaunchHistory, *, max_items: int = 8) -> str:
    lines: list[str] = []
    total = history.total_created or len(history.tokens)
    lines.append(
        f"<b>Dev 全链发射历史</b>：约 {total} 枚"
        f"（bonding {history.inner_count} / graduated {history.open_count}）"
    )
    if history.ath_mc > 0:
        if history.ath_token:
            lines.append(
                f"历史最高 ATH MC：<b>{_fmt_usd(history.ath_mc)}</b> "
                f"{_e(history.ath_symbol)} <code>{_e(history.ath_token[:12])}…</code>"
            )
        else:
            lines.append(
                f"历史最高 ATH MC：<b>{_fmt_usd(history.ath_mc)}</b> {_e(history.ath_symbol)}"
            )
    for t in history.tokens[:max_items]:
        lines.append(
            f"• [{_e(t.chain)}] {_e(t.symbol or '?')} "
            f"ATH {_fmt_usd(t.token_ath_mc)} / MC {_fmt_usd(t.market_cap)} "
            f"<code>{_e(t.token_address)}</code>"
        )
    if len(history.tokens) > max_items:
        lines.append(f"… 另有 {len(history.tokens) - max_items} 枚未列出")
    if not history.tokens:
        lines.append("（暂无查询到历史发射记录）")
    return "\n".join(lines)


def format_twitter_alert(
    *,
    token: TokenInfo,
    tweets: Iterable[TweetMatch],
    history: DevLaunchHistory,
    twitter_progress: str,
    dev_progress: str,
    follower_threshold: int,
) -> str:
    tags = "[推特大V]"
    tweet_lines: list[str] = []
    for tw in tweets:
        tweet_lines.append(
            f"• @{_e(tw.author_username)} · 粉丝 {_e(tw.followers_count)} "
            f"(>{follower_threshold})\n"
            f'  <a href="{_e(tw.url)}">查看推文</a>'
        )
    body = "\n".join(
        [
            f"<b>{tags}</b>",
            f"代币：<b>{_e(token.symbol)}</b> {_e(token.name)}",
            f"链：{_e(token.chain)}",
            f"合约：<code>{_e(token.address)}</code>",
            f"MC：{_fmt_usd(token.market_cap)} · 流动性：{_fmt_usd(token.liquidity)}",
            f"Launchpad：{_e(token.launchpad_platform or '-')}",
            f"Dev：<code>{_e(token.creator_address)}</code>",
            f'<a href="{_e(token.gmgn_token_url())}">GMGN Token</a> · '
            f'<a href="{_e(token.gmgn_wallet_url())}">GMGN Wallet</a>',
            "",
            "<b>匹配推文</b>：",
            *tweet_lines,
            "",
            _history_block(history),
            "",
            f"惯犯进度 · Twitter {twitter_progress} · Dev {dev_progress}",
        ]
    )
    return body


def format_high_ath_alert(
    *,
    token: TokenInfo,
    history: DevLaunchHistory,
    prior: list[CreatedToken],
    threshold: float,
    twitter_progress: str,
    dev_progress: str,
) -> str:
    tags = "[高ATH Dev]"
    prior_lines = [
        f"• [{_e(t.chain)}] {_e(t.symbol or '?')} "
        f"ATH <b>{_fmt_usd(t.token_ath_mc)}</b> "
        f"<code>{_e(t.token_address)}</code>"
        for t in prior[:10]
    ]
    if not prior_lines and history.ath_mc >= threshold:
        prior_lines = [
            f"• ATH {_fmt_usd(history.ath_mc)} {_e(history.ath_symbol)} "
            f"<code>{_e(history.ath_token)}</code>"
        ]
    body = "\n".join(
        [
            f"<b>{tags}</b>",
            f"代币：<b>{_e(token.symbol)}</b> {_e(token.name)}",
            f"链：{_e(token.chain)}",
            f"合约：<code>{_e(token.address)}</code>",
            f"MC：{_fmt_usd(token.market_cap)} · 流动性：{_fmt_usd(token.liquidity)}",
            f"Dev：<code>{_e(token.creator_address)}</code>",
            f'<a href="{_e(token.gmgn_token_url())}">GMGN Token</a> · '
            f'<a href="{_e(token.gmgn_wallet_url())}">GMGN Wallet</a>',
            "",
            f"该 Dev 曾发射 ATH MC ≥ {_fmt_usd(threshold)} 的代币：",
            *prior_lines,
            "",
            _history_block(history),
            "",
            f"惯犯进度 · Twitter {twitter_progress} · Dev {dev_progress}",
        ]
    )
    return body


def format_dev_lookup(token: TokenInfo | None, history: DevLaunchHistory, address: str) -> str:
    lines = [
        f"<b>Dev 查询</b>：<code>{_e(address)}</code>",
        f'<a href="https://gmgn.ai/robinhood/address/{_e(address)}">GMGN Wallet</a>',
        "",
        _history_block(history, max_items=15),
    ]
    if token:
        lines.insert(
            1,
            f"关联代币示例：{_e(token.symbol)} <code>{_e(token.address)}</code>",
        )
    return "\n".join(lines)
