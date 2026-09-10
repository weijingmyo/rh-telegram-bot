"""New-token scan pipeline."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import structlog

from src.alerts import (
    AlertSender,
    format_high_ath_alert,
    format_twitter_alert,
)
from src.blacklist import BlacklistService, has_high_ath, should_alert_followers
from src.config import Settings
from src.gmgn import DevLaunchHistory, GmgnClient, TokenInfo
from src.storage import Database
from src.twitter import TweetMatch, TwitterProvider

log = structlog.get_logger(__name__)

REASON_TWITTER = "twitter_kol"
REASON_HIGH_ATH = "high_ath_dev"


@dataclass
class ScannerStats:
    cycles: int = 0
    tokens_seen: int = 0
    alerts_sent: int = 0
    last_cycle_at: str | None = None
    last_error: str | None = None
    running: bool = False


@dataclass
class TokenScanner:
    settings: Settings
    db: Database
    gmgn: GmgnClient
    twitter: TwitterProvider
    blacklist: BlacklistService
    alerts: AlertSender
    stats: ScannerStats = field(default_factory=ScannerStats)
    _task: asyncio.Task[None] | None = field(default=None, repr=False)
    _stop: asyncio.Event = field(default_factory=asyncio.Event, repr=False)

    async def start(self) -> None:
        if self._task and not self._task.done():
            return
        self._stop.clear()
        self.stats.running = True
        await self.db.set_state("scanner_running", True)
        self._task = asyncio.create_task(self._loop(), name="token-scanner")
        log.info("scanner.started", chains=self.settings.chain_list)

    async def stop(self) -> None:
        self._stop.set()
        self.stats.running = False
        await self.db.set_state("scanner_running", False)
        if self._task:
            try:
                await asyncio.wait_for(self._task, timeout=5)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                self._task.cancel()
            self._task = None
        log.info("scanner.stopped")

    async def _loop(self) -> None:
        # Warm-up: mark current trenches as seen so we only alert on NEW ones
        await self._bootstrap_seen()
        while not self._stop.is_set():
            try:
                await self.run_once()
            except Exception as exc:  # noqa: BLE001
                self.stats.last_error = str(exc)
                log.exception("scanner.cycle_error", error=str(exc))
            self.stats.cycles += 1
            self.stats.last_cycle_at = datetime.now(timezone.utc).isoformat()
            try:
                await asyncio.wait_for(
                    self._stop.wait(),
                    timeout=self.settings.scan_interval_seconds,
                )
                break
            except asyncio.TimeoutError:
                continue

    async def _bootstrap_seen(self) -> None:
        for chain in self.settings.chain_list:
            tokens = await self.gmgn.fetch_new_creations(chain)
            for t in tokens:
                await self.db.mark_token_seen(chain, t.address)
            log.info("scanner.bootstrap", chain=chain, marked=len(tokens))

    async def run_once(self) -> None:
        for chain in self.settings.chain_list:
            tokens = await self.gmgn.fetch_new_creations(chain)
            for trench in tokens:
                if await self.db.is_token_seen(chain, trench.address):
                    continue
                await self.db.mark_token_seen(chain, trench.address)
                self.stats.tokens_seen += 1
                await self._process_token(trench)
                await asyncio.sleep(0.4)

    async def _process_token(self, trench: TokenInfo) -> None:
        chain = trench.chain
        address = trench.address
        log.info("scanner.new_token", chain=chain, address=address, symbol=trench.symbol)

        info = await self.gmgn.fetch_token_info(chain, address) or trench
        if not info.creator_address and trench.creator_address:
            info.creator_address = trench.creator_address
        if not info.market_cap and trench.market_cap:
            info.market_cap = trench.market_cap
        if not info.liquidity and trench.liquidity:
            info.liquidity = trench.liquidity

        creator = info.creator_address
        if not creator:
            log.warning("scanner.no_creator", address=address)
            return

        # Blacklist gate on dev
        dev_check = await self.blacklist.check("dev", creator)
        if not dev_check.allowed:
            log.info("scanner.skip_blacklisted_dev", creator=creator)
            return

        # Launch history (full chain)
        history = await self.gmgn.fetch_full_launch_history(creator)

        # Prefer ath from token.info.dev.ath_token_info when higher
        if info.ath_token_info and info.ath_token_info.ath_mc > history.ath_mc:
            history.ath_mc = info.ath_token_info.ath_mc
            history.ath_symbol = info.ath_token_info.symbol
            history.ath_token = info.ath_token_info.ath_token

        # --- Reason 1: Twitter KOL ---
        await self._maybe_twitter_alert(info, history, creator)

        # --- Reason 2: High ATH Dev ---
        await self._maybe_ath_alert(info, history, creator)

    async def _maybe_twitter_alert(
        self,
        info: TokenInfo,
        history: DevLaunchHistory,
        creator: str,
    ) -> None:
        if await self.db.has_alert_pair(info.chain, info.address, REASON_TWITTER):
            return
        if not self.twitter.configured:
            return

        matches = await self.twitter.search_address(creator)
        big: list[TweetMatch] = [
            m
            for m in matches
            if should_alert_followers(m.followers_count, self.settings.follower_threshold)
        ]
        if not big:
            return

        # Skip if any author already blacklisted
        eligible: list[TweetMatch] = []
        for m in big:
            tw_check = await self.blacklist.check("twitter", m.author_username)
            if tw_check.allowed:
                eligible.append(m)
            else:
                log.info("scanner.skip_blacklisted_twitter", user=m.author_username)
        if not eligible:
            return

        # Record counts for each twitter author + dev (once per alert)
        tw_progress = "0/3"
        for m in eligible:
            dec = await self.blacklist.record_alert("twitter", m.author_username)
            tw_progress = dec.progress
        dev_dec = await self.blacklist.record_alert("dev", creator)

        text = format_twitter_alert(
            token=info,
            tweets=eligible,
            history=history,
            twitter_progress=tw_progress,
            dev_progress=dev_dec.progress,
            follower_threshold=self.settings.follower_threshold,
        )
        sent = await self.alerts.send_html(text)
        await self.db.mark_alert_pair(info.chain, info.address, REASON_TWITTER)
        self.stats.alerts_sent += sent
        log.info("scanner.twitter_alert", address=info.address, sent=sent)

    async def _maybe_ath_alert(
        self,
        info: TokenInfo,
        history: DevLaunchHistory,
        creator: str,
    ) -> None:
        if await self.db.has_alert_pair(info.chain, info.address, REASON_HIGH_ATH):
            return

        # Spec: after 3 cumulative alerts never alert again
        dev_before = await self.blacklist.check("dev", creator)
        if not dev_before.allowed:
            return

        prior = [
            t
            for t in history.tokens_above_ath(self.settings.ath_mc_threshold)
            if t.token_address.lower() != info.address.lower()
        ]

        # Prefer prior launches; fall back to ath_token_info only if it is a different token
        ath_from_info = False
        if info.ath_token_info and info.ath_token_info.ath_token:
            if info.ath_token_info.ath_token.lower() != info.address.lower():
                ath_from_info = has_high_ath(
                    info.ath_token_info.ath_mc, self.settings.ath_mc_threshold
                )

        ath_hit = bool(prior) or ath_from_info or (
            has_high_ath(history.ath_mc, self.settings.ath_mc_threshold) and bool(prior)
        )
        if not ath_hit:
            return

        if not prior and info.ath_token_info and ath_from_info:
            # synthesize a prior entry for the message
            from src.gmgn.models import CreatedToken

            prior = [
                CreatedToken(
                    token_address=info.ath_token_info.ath_token,
                    symbol=info.ath_token_info.symbol,
                    name=info.ath_token_info.name,
                    token_ath_mc=info.ath_token_info.ath_mc,
                )
            ]

        if not prior:
            return

        dev_dec = await self.blacklist.record_alert("dev", creator)
        text = format_high_ath_alert(
            token=info,
            history=history,
            prior=prior,
            threshold=self.settings.ath_mc_threshold,
            twitter_progress="-",
            dev_progress=dev_dec.progress,
        )
        sent = await self.alerts.send_html(text)
        await self.db.mark_alert_pair(info.chain, info.address, REASON_HIGH_ATH)
        self.stats.alerts_sent += sent
        log.info("scanner.ath_alert", address=info.address, sent=sent)

    def status_dict(self) -> dict[str, Any]:
        return {
            "running": self.stats.running,
            "cycles": self.stats.cycles,
            "tokens_seen": self.stats.tokens_seen,
            "alerts_sent": self.stats.alerts_sent,
            "last_cycle_at": self.stats.last_cycle_at,
            "last_error": self.stats.last_error,
            "chains": self.settings.chain_list,
            "twitter_configured": self.twitter.configured,
            "telegram_configured": self.settings.telegram_configured,
        }
