"""GMGN domain models."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


def _as_float(value: Any, default: float = 0.0) -> float:
    if value is None or value == "":
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


@dataclass
class AthTokenInfo:
    ath_token: str = ""
    ath_mc: float = 0.0
    symbol: str = ""
    name: str = ""
    creation_timestamp: int | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> AthTokenInfo | None:
        if not data:
            return None
        return cls(
            ath_token=str(data.get("ath_token") or ""),
            ath_mc=_as_float(data.get("ath_mc")),
            symbol=str(data.get("symbol") or data.get("token_symbol") or ""),
            name=str(data.get("name") or data.get("token_name") or ""),
            creation_timestamp=(
                int(data["creation_timestamp"])
                if data.get("creation_timestamp") not in (None, "")
                else None
            ),
        )


@dataclass
class CreatedToken:
    token_address: str
    symbol: str = ""
    name: str = ""
    chain: str = ""
    market_cap: float = 0.0
    token_ath_mc: float = 0.0
    pool_liquidity: float = 0.0
    create_timestamp: int | None = None
    is_open: bool = False
    launchpad_platform: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any], default_chain: str = "") -> CreatedToken:
        return cls(
            token_address=str(
                data.get("token_address") or data.get("address") or ""
            ),
            symbol=str(data.get("symbol") or ""),
            name=str(data.get("name") or data.get("token_name") or ""),
            chain=str(data.get("chain") or default_chain),
            market_cap=_as_float(data.get("market_cap")),
            token_ath_mc=_as_float(data.get("token_ath_mc") or data.get("ath_mc")),
            pool_liquidity=_as_float(data.get("pool_liquidity") or data.get("liquidity")),
            create_timestamp=(
                int(data["create_timestamp"])
                if data.get("create_timestamp") not in (None, "")
                else (
                    int(data["creation_timestamp"])
                    if data.get("creation_timestamp") not in (None, "")
                    else None
                )
            ),
            is_open=bool(data.get("is_open")),
            launchpad_platform=str(data.get("launchpad_platform") or ""),
        )


@dataclass
class TokenInfo:
    address: str
    chain: str
    symbol: str = ""
    name: str = ""
    liquidity: float = 0.0
    market_cap: float = 0.0
    price: float = 0.0
    creator_address: str = ""
    launchpad_platform: str = ""
    creation_timestamp: int | None = None
    ath_token_info: AthTokenInfo | None = None
    creator_open_count: int = 0
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_trenches_item(cls, data: dict[str, Any], chain: str) -> TokenInfo:
        address = str(data.get("address") or data.get("token_address") or "")
        mc = _as_float(
            data.get("usd_market_cap")
            or data.get("market_cap")
            or data.get("marketcap")
        )
        return cls(
            address=address,
            chain=chain,
            symbol=str(data.get("symbol") or ""),
            name=str(data.get("name") or ""),
            liquidity=_as_float(data.get("liquidity")),
            market_cap=mc,
            price=_as_float(data.get("price")),
            creator_address=str(data.get("creator") or data.get("creator_address") or ""),
            launchpad_platform=str(data.get("launchpad_platform") or ""),
            creation_timestamp=(
                int(data["created_timestamp"])
                if data.get("created_timestamp") not in (None, "")
                else (
                    int(data["creation_timestamp"])
                    if data.get("creation_timestamp") not in (None, "")
                    else None
                )
            ),
            raw=data,
        )

    @classmethod
    def from_token_info(cls, data: dict[str, Any], chain: str) -> TokenInfo:
        # CLI --raw may wrap under data
        body = data.get("data", data) if isinstance(data, dict) else {}
        if not isinstance(body, dict):
            body = {}
        # Sometimes double-wrapped
        if "address" not in body and isinstance(body.get("data"), dict):
            body = body["data"]

        price_obj = body.get("price") or {}
        price_val = (
            _as_float(price_obj.get("price"))
            if isinstance(price_obj, dict)
            else _as_float(price_obj)
        )
        circulating = _as_float(body.get("circulating_supply") or body.get("total_supply"))
        mc = price_val * circulating if price_val and circulating else _as_float(
            body.get("market_cap") or body.get("usd_market_cap")
        )
        dev = body.get("dev") or {}
        if not isinstance(dev, dict):
            dev = {}
        ath = AthTokenInfo.from_dict(dev.get("ath_token_info"))
        return cls(
            address=str(body.get("address") or ""),
            chain=chain,
            symbol=str(body.get("symbol") or ""),
            name=str(body.get("name") or ""),
            liquidity=_as_float(body.get("liquidity")),
            market_cap=mc,
            price=price_val,
            creator_address=str(dev.get("creator_address") or ""),
            launchpad_platform=str(
                body.get("launchpad_platform") or body.get("launchpad") or ""
            ),
            creation_timestamp=(
                int(body["creation_timestamp"])
                if body.get("creation_timestamp") not in (None, "")
                else None
            ),
            ath_token_info=ath,
            creator_open_count=int(dev.get("creator_open_count") or 0),
            raw=body,
        )

    def gmgn_token_url(self) -> str:
        return f"https://gmgn.ai/{self.chain}/token/{self.address}"

    def gmgn_wallet_url(self, wallet: str | None = None) -> str:
        w = wallet or self.creator_address
        return f"https://gmgn.ai/{self.chain}/address/{w}"


@dataclass
class DevLaunchHistory:
    wallet: str
    tokens: list[CreatedToken] = field(default_factory=list)
    ath_mc: float = 0.0
    ath_symbol: str = ""
    ath_token: str = ""
    inner_count: int = 0
    open_count: int = 0

    @property
    def total_created(self) -> int:
        return self.inner_count + self.open_count

    def tokens_above_ath(self, threshold: float) -> list[CreatedToken]:
        return [t for t in self.tokens if t.token_ath_mc >= threshold]
