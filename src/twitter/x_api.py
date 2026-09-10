"""X API v2 recent search client."""

from __future__ import annotations

import asyncio
from typing import Any
import aiohttp
import structlog

from src.config import Settings
from src.twitter.base import NullTwitterProvider, TweetMatch, TwitterProvider

log = structlog.get_logger(__name__)

SEARCH_URL = "https://api.twitter.com/2/tweets/search/recent"


class XApiTwitterProvider(TwitterProvider):
    """
    Uses X API v2 recent search.

    Required env (any one auth path):
      - TWITTER_BEARER_TOKEN  (preferred)
      - or OAuth 1.0a:
          TWITTER_API_KEY, TWITTER_API_SECRET,
          TWITTER_ACCESS_TOKEN, TWITTER_ACCESS_TOKEN_SECRET

    Query: exact wallet address as a phrase when possible.
    Expansions: author_id + public_metrics for followers_count.
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._session: aiohttp.ClientSession | None = None
        self._min_interval = 1.1  # basic rate-limit pacing
        self._last_call = 0.0

    @property
    def configured(self) -> bool:
        return self.settings.twitter_configured

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()

    def _headers(self) -> dict[str, str]:
        if self.settings.twitter_bearer_token:
            return {
                "Authorization": f"Bearer {self.settings.twitter_bearer_token}",
                "User-Agent": "rh-telegram-bot/1.0",
            }
        # OAuth1 would need signing library; document Bearer as primary path.
        raise RuntimeError(
            "TWITTER_BEARER_TOKEN required for X API v2 recent search "
            "(OAuth1 user-context not implemented; provide Bearer Token)"
        )

    async def _throttle(self) -> None:
        loop = asyncio.get_event_loop()
        now = loop.time()
        wait = self._min_interval - (now - self._last_call)
        if wait > 0:
            await asyncio.sleep(wait)
        self._last_call = loop.time()

    async def search_address(self, address: str, *, max_results: int = 20) -> list[TweetMatch]:
        if not self.configured:
            return []
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=30)
            )

        # Prefer exact phrase match; also allow bare address
        query = f'"{address}" -is:retweet'
        params = {
            "query": query,
            "max_results": str(min(max(10, max_results), 100)),
            "tweet.fields": "created_at,author_id,text,entities,public_metrics",
            "expansions": "author_id",
            "user.fields": "username,name,public_metrics,verified,verified_type",
        }

        await self._throttle()
        try:
            headers = self._headers()
        except RuntimeError as exc:
            log.warning("twitter.auth_error", error=str(exc))
            return []

        try:
            async with self._session.get(SEARCH_URL, headers=headers, params=params) as resp:
                text = await resp.text()
                if resp.status == 429:
                    reset = resp.headers.get("x-rate-limit-reset")
                    log.warning("twitter.rate_limited", reset=reset)
                    await asyncio.sleep(15)
                    return []
                if resp.status >= 400:
                    log.warning("twitter.search_failed", status=resp.status, body=text[:400])
                    return []
                payload: dict[str, Any] = await resp.json() if resp.content_type == "application/json" else {}
                if not payload and text:
                    import json

                    payload = json.loads(text)
        except Exception as exc:  # noqa: BLE001
            log.warning("twitter.search_error", error=str(exc))
            return []

        users: dict[str, dict[str, Any]] = {}
        for u in (payload.get("includes") or {}).get("users") or []:
            users[str(u.get("id"))] = u

        matches: list[TweetMatch] = []
        for tw in payload.get("data") or []:
            # Verify exact address appears in text (case-insensitive for EVM hex)
            tw_text = str(tw.get("text") or "")
            if address not in tw_text and address.lower() not in tw_text.lower():
                continue
            author_id = str(tw.get("author_id") or "")
            user = users.get(author_id) or {}
            metrics = user.get("public_metrics") or {}
            username = str(user.get("username") or "")
            tweet_id = str(tw.get("id") or "")
            url = f"https://x.com/{username}/status/{tweet_id}" if username else f"https://x.com/i/web/status/{tweet_id}"
            matches.append(
                TweetMatch(
                    tweet_id=tweet_id,
                    text=tw_text,
                    url=url,
                    author_id=author_id,
                    author_username=username,
                    author_name=str(user.get("name") or ""),
                    followers_count=int(metrics.get("followers_count") or 0),
                    verified=bool(user.get("verified")),
                    raw=tw,
                )
            )
        log.info(
            "twitter.search_ok",
            address=address[:12] + "…",
            hits=len(matches),
        )
        return matches


def build_twitter_provider(settings: Settings) -> TwitterProvider:
    if settings.twitter_configured:
        if not settings.twitter_bearer_token:
            log.warning(
                "twitter.oauth1_only",
                msg="Bearer token missing; falling back to NullTwitterProvider "
                "(implement OAuth1 or set TWITTER_BEARER_TOKEN)",
            )
            return NullTwitterProvider()
        return XApiTwitterProvider(settings)
    log.warning("twitter.disabled", msg="No Twitter credentials; tweet scan skipped")
    return NullTwitterProvider()
