"""Blacklist / 惯犯 tracking."""

from __future__ import annotations

from dataclasses import dataclass

from src.storage import Database, EntityAlertState


@dataclass
class BlacklistDecision:
    allowed: bool
    entity: EntityAlertState
    progress: str  # e.g. "2/3"


class BlacklistService:
    def __init__(self, db: Database, limit: int = 3) -> None:
        self.db = db
        self.limit = limit

    def progress_label(self, count: int) -> str:
        return f"{count}/{self.limit}"

    async def check(self, entity_type: str, entity_key: str) -> BlacklistDecision:
        entity = await self.db.get_entity(entity_type, entity_key)
        return BlacklistDecision(
            allowed=not entity.blacklisted,
            entity=entity,
            progress=self.progress_label(entity.alert_count),
        )

    async def record_alert(self, entity_type: str, entity_key: str) -> BlacklistDecision:
        """Record one alert; may flip to blacklisted when reaching limit."""
        entity = await self.db.increment_entity_alert(
            entity_type, entity_key, limit=self.limit
        )
        return BlacklistDecision(
            allowed=not entity.blacklisted or entity.alert_count <= self.limit,
            entity=entity,
            progress=self.progress_label(entity.alert_count),
        )

    async def list_all(self, limit: int = 50) -> list[EntityAlertState]:
        return await self.db.list_blacklist(limit=limit)


def should_alert_followers(followers: int, threshold: int) -> bool:
    """Pure helper used by scanner + unit tests."""
    return followers > threshold


def has_high_ath(ath_mc: float, threshold: float) -> bool:
    """True when prior ATH market cap meets/exceeds threshold (USD)."""
    return ath_mc >= threshold
