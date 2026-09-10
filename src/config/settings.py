"""Application settings loaded from environment variables."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Telegram
    telegram_bot_token: str = ""
    telegram_chat_ids: str = ""

    # Twitter / X
    twitter_bearer_token: str = ""
    twitter_api_key: str = ""
    twitter_api_secret: str = ""
    twitter_access_token: str = ""
    twitter_access_token_secret: str = ""

    # GMGN
    gmgn_api_key: str = ""
    gmgn_mode: Literal["cli", "http"] = "cli"
    gmgn_cli_bin: str = "npx"
    gmgn_cli_package: str = "gmgn-cli"
    gmgn_http_base_url: str = "https://openapi.gmgn.ai"
    gmgn_cli_timeout_seconds: float = 60.0

    # Scan / thresholds
    scan_chains: str = "robinhood"
    scan_interval_seconds: float = 30.0
    follower_threshold: int = 10000
    ath_mc_threshold: float = 800_000.0
    blacklist_alert_limit: int = 3
    trenches_limit: int = 50

    # Runtime
    database_path: str = "data/bot.db"
    log_level: str = "INFO"
    health_host: str = "0.0.0.0"
    health_port: int = 8080
    auto_start_scanner: bool = True

    @field_validator("scan_chains", mode="before")
    @classmethod
    def _strip_chains(cls, v: object) -> object:
        return v

    @property
    def chain_list(self) -> list[str]:
        return [c.strip() for c in self.scan_chains.split(",") if c.strip()]

    @property
    def chat_id_list(self) -> list[int]:
        ids: list[int] = []
        for part in self.telegram_chat_ids.split(","):
            part = part.strip()
            if not part:
                continue
            try:
                ids.append(int(part))
            except ValueError:
                continue
        return ids

    @property
    def db_path(self) -> Path:
        return Path(self.database_path)

    @property
    def telegram_configured(self) -> bool:
        return bool(self.telegram_bot_token.strip())

    @property
    def twitter_configured(self) -> bool:
        return bool(self.twitter_bearer_token.strip()) or (
            bool(self.twitter_api_key.strip())
            and bool(self.twitter_api_secret.strip())
            and bool(self.twitter_access_token.strip())
            and bool(self.twitter_access_token_secret.strip())
        )

    @property
    def gmgn_configured(self) -> bool:
        return bool(self.gmgn_api_key.strip()) or self.gmgn_mode == "cli"


@lru_cache
def get_settings() -> Settings:
    return Settings()
