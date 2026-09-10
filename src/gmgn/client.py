"""GMGN client — prefers `npx gmgn-cli ... --raw` subprocess; optional HTTP fallback."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import shutil
from typing import Any

import aiohttp
import structlog

from src.config import Settings
from src.gmgn.models import CreatedToken, DevLaunchHistory, TokenInfo, _as_float

log = structlog.get_logger(__name__)

# Chains to query for full-chain launch history
HISTORY_CHAINS = ["robinhood", "sol", "bsc", "base", "eth"]


class GmgnError(Exception):
    pass


class GmgnClient:
    """
    Primary implementation: subprocess
      npx gmgn-cli <cmd...> --raw

    HTTP mode calls the same OpenAPI routes the CLI uses
    (documented in gmgn-skills):
      POST /v1/trenches
      GET  /v1/token/info
      GET  /v1/user/created_tokens

    Auth: GMGN_API_KEY via env (CLI reads ~/.config/gmgn/.env or process env).
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._session: aiohttp.ClientSession | None = None
        self._available: bool | None = None
        self._cli_path: str | None = None

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()

    def _ensure_api_key_env(self) -> None:
        if self.settings.gmgn_api_key and not os.environ.get("GMGN_API_KEY"):
            os.environ["GMGN_API_KEY"] = self.settings.gmgn_api_key

    async def check_available(self) -> bool:
        if self._available is not None:
            return self._available
        if self.settings.gmgn_mode == "http":
            self._available = bool(self.settings.gmgn_api_key)
            if not self._available:
                log.warning("gmgn.http_missing_key", msg="GMGN_API_KEY missing; GMGN HTTP disabled")
            return self._available

        self._ensure_api_key_env()
        # Prefer global gmgn-cli, else npx
        which = shutil.which("gmgn-cli")
        if which:
            self._cli_path = which
            self._available = True
            log.info("gmgn.cli_found", path=which)
            return True
        if shutil.which(self.settings.gmgn_cli_bin):
            self._cli_path = None  # use npx
            self._available = True
            log.info("gmgn.npx_available", bin=self.settings.gmgn_cli_bin)
            return True
        self._available = False
        log.warning(
            "gmgn.cli_missing",
            msg="gmgn-cli / npx not found; GMGN calls will be skipped",
        )
        return False

    async def _run_cli(self, args: list[str]) -> dict[str, Any]:
        self._ensure_api_key_env()
        # Ensure npm local dirs exist (npx may fail with ENOENT on missing prefix)
        try:
            Path(os.path.expanduser("~/.local/lib")).mkdir(parents=True, exist_ok=True)
            Path(os.path.expanduser("~/.npm")).mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
        if self._cli_path:
            cmd = [self._cli_path, *args, "--raw"]
        else:
            cmd = [
                self.settings.gmgn_cli_bin,
                "--yes",
                self.settings.gmgn_cli_package,
                *args,
                "--raw",
            ]
        log.debug("gmgn.cli_exec", cmd=" ".join(cmd))
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=os.environ.copy(),
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(),
                timeout=self.settings.gmgn_cli_timeout_seconds,
            )
        except asyncio.TimeoutError as exc:
            raise GmgnError(f"gmgn-cli timeout: {' '.join(args)}") from exc
        except FileNotFoundError as exc:
            raise GmgnError("gmgn-cli executable not found") from exc

        out = stdout.decode("utf-8", errors="replace").strip()
        err = stderr.decode("utf-8", errors="replace").strip()
        if proc.returncode != 0:
            raise GmgnError(
                f"gmgn-cli failed ({proc.returncode}): {err or out or 'no output'}"
            )
        if not out:
            raise GmgnError(f"gmgn-cli empty stdout: {err}")
        # CLI may print notices on stderr; stdout should be JSON
        # Sometimes multiple lines — take last JSON-looking line
        line = out.splitlines()[-1]
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            # try full stdout
            try:
                payload = json.loads(out)
            except json.JSONDecodeError as exc:
                raise GmgnError(f"invalid JSON from gmgn-cli: {out[:500]}") from exc
        if isinstance(payload, dict) and "data" in payload and len(payload) <= 3:
            # unwrap common envelope {code, data, message}
            data = payload["data"]
            if isinstance(data, dict):
                return data
            return payload
        if isinstance(payload, dict):
            return payload
        return {"data": payload}

    async def _http(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        if not self.settings.gmgn_api_key:
            raise GmgnError("GMGN_API_KEY required for HTTP mode")
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=self.settings.gmgn_cli_timeout_seconds)
            )
        url = f"{self.settings.gmgn_http_base_url.rstrip('/')}{path}"
        headers = {
            "Authorization": f"Bearer {self.settings.gmgn_api_key}",
            "X-API-KEY": self.settings.gmgn_api_key,
            "Accept": "application/json",
        }
        async with self._session.request(method, url, headers=headers, **kwargs) as resp:
            text = await resp.text()
            if resp.status == 429:
                raise GmgnError(f"rate limited: {text[:300]}")
            if resp.status >= 400:
                raise GmgnError(f"HTTP {resp.status}: {text[:300]}")
            try:
                payload = json.loads(text)
            except json.JSONDecodeError as exc:
                raise GmgnError(f"invalid JSON: {text[:300]}") from exc
            if isinstance(payload, dict) and "data" in payload:
                data = payload["data"]
                return data if isinstance(data, dict) else {"data": data}
            return payload if isinstance(payload, dict) else {"data": payload}

    async def fetch_new_creations(self, chain: str, limit: int | None = None) -> list[TokenInfo]:
        if not await self.check_available():
            return []
        limit = limit or self.settings.trenches_limit
        try:
            if self.settings.gmgn_mode == "http":
                data = await self._http(
                    "POST",
                    "/v1/trenches",
                    json={
                        "chain": chain,
                        "type": ["new_creation"],
                        "limit": limit,
                    },
                )
            else:
                data = await self._run_cli(
                    [
                        "market",
                        "trenches",
                        "--chain",
                        chain,
                        "--type",
                        "new_creation",
                        "--limit",
                        str(limit),
                    ]
                )
        except GmgnError as exc:
            log.warning("gmgn.trenches_failed", chain=chain, error=str(exc))
            return []

        items = data.get("new_creation") or data.get("list") or []
        if not isinstance(items, list):
            items = []
        tokens: list[TokenInfo] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            t = TokenInfo.from_trenches_item(item, chain)
            if t.address:
                tokens.append(t)
        log.info("gmgn.trenches_ok", chain=chain, count=len(tokens))
        return tokens

    async def fetch_token_info(self, chain: str, address: str) -> TokenInfo | None:
        if not await self.check_available():
            return None
        try:
            if self.settings.gmgn_mode == "http":
                data = await self._http(
                    "GET",
                    "/v1/token/info",
                    params={"chain": chain, "address": address},
                )
            else:
                data = await self._run_cli(
                    ["token", "info", "--chain", chain, "--address", address]
                )
        except GmgnError as exc:
            log.warning("gmgn.token_info_failed", chain=chain, address=address, error=str(exc))
            return None
        info = TokenInfo.from_token_info(data, chain)
        if not info.address:
            info.address = address
        return info

    async def fetch_created_tokens(
        self, chain: str, wallet: str
    ) -> DevLaunchHistory:
        empty = DevLaunchHistory(wallet=wallet)
        if not await self.check_available():
            return empty
        try:
            if self.settings.gmgn_mode == "http":
                data = await self._http(
                    "GET",
                    "/v1/user/created_tokens",
                    params={
                        "chain": chain,
                        "wallet": wallet,
                        "order_by": "token_ath_mc",
                        "direction": "desc",
                    },
                )
            else:
                data = await self._run_cli(
                    [
                        "portfolio",
                        "created-tokens",
                        "--chain",
                        chain,
                        "--wallet",
                        wallet,
                        "--order-by",
                        "token_ath_mc",
                        "--direction",
                        "desc",
                    ]
                )
        except GmgnError as exc:
            log.debug(
                "gmgn.created_tokens_failed",
                chain=chain,
                wallet=wallet,
                error=str(exc),
            )
            return empty

        # envelope variations
        body = data
        if "tokens" not in body and isinstance(body.get("data"), dict):
            body = body["data"]

        tokens_raw = body.get("tokens") or []
        tokens = [
            CreatedToken.from_dict(t, default_chain=chain)
            for t in tokens_raw
            if isinstance(t, dict)
        ]
        ath_info = body.get("creator_ath_info") or {}
        ath_mc = _as_float(ath_info.get("ath_mc"))
        if not ath_mc and tokens:
            ath_mc = max((t.token_ath_mc for t in tokens), default=0.0)
        return DevLaunchHistory(
            wallet=wallet,
            tokens=tokens,
            ath_mc=ath_mc,
            ath_symbol=str(
                ath_info.get("token_symbol") or ath_info.get("symbol") or ""
            ),
            ath_token=str(ath_info.get("ath_token") or ""),
            inner_count=int(body.get("inner_count") or 0),
            open_count=int(body.get("open_count") or 0),
        )

    async def fetch_full_launch_history(self, wallet: str) -> DevLaunchHistory:
        """Aggregate created-tokens across known chains."""
        merged: list[CreatedToken] = []
        best_ath = 0.0
        best_symbol = ""
        best_token = ""
        inner = 0
        open_c = 0
        for chain in HISTORY_CHAINS:
            hist = await self.fetch_created_tokens(chain, wallet)
            merged.extend(hist.tokens)
            inner += hist.inner_count
            open_c += hist.open_count
            if hist.ath_mc > best_ath:
                best_ath = hist.ath_mc
                best_symbol = hist.ath_symbol
                best_token = hist.ath_token
            # small delay to be rate-limit friendly
            await asyncio.sleep(0.35)
        # dedupe by (chain, address)
        seen: set[str] = set()
        unique: list[CreatedToken] = []
        for t in sorted(merged, key=lambda x: x.token_ath_mc, reverse=True):
            key = f"{t.chain}:{t.token_address.lower()}"
            if key in seen or not t.token_address:
                continue
            seen.add(key)
            unique.append(t)
        if not best_ath and unique:
            best_ath = unique[0].token_ath_mc
            best_symbol = unique[0].symbol
            best_token = unique[0].token_address
        return DevLaunchHistory(
            wallet=wallet,
            tokens=unique,
            ath_mc=best_ath,
            ath_symbol=best_symbol,
            ath_token=best_token,
            inner_count=inner,
            open_count=open_c,
        )
