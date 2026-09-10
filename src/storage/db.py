"""SQLite persistence layer (aiosqlite)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import aiosqlite


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


SCHEMA = """
CREATE TABLE IF NOT EXISTS seen_tokens (
    chain TEXT NOT NULL,
    address TEXT NOT NULL,
    first_seen_at TEXT NOT NULL,
    PRIMARY KEY (chain, address)
);

CREATE TABLE IF NOT EXISTS alert_pairs (
    chain TEXT NOT NULL,
    token_address TEXT NOT NULL,
    reason TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (chain, token_address, reason)
);

CREATE TABLE IF NOT EXISTS entity_alerts (
    entity_type TEXT NOT NULL,  -- 'twitter' | 'dev'
    entity_key TEXT NOT NULL,
    alert_count INTEGER NOT NULL DEFAULT 0,
    blacklisted INTEGER NOT NULL DEFAULT 0,
    blacklisted_at TEXT,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (entity_type, entity_key)
);

CREATE TABLE IF NOT EXISTS subscribers (
    chat_id INTEGER PRIMARY KEY,
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS bot_state (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""


@dataclass
class EntityAlertState:
    entity_type: str
    entity_key: str
    alert_count: int
    blacklisted: bool


class Database:
    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self._conn: aiosqlite.Connection | None = None

    async def connect(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = await aiosqlite.connect(self.path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.executescript(SCHEMA)
        await self._conn.commit()

    async def close(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None

    @property
    def conn(self) -> aiosqlite.Connection:
        if self._conn is None:
            raise RuntimeError("Database not connected")
        return self._conn

    # --- seen tokens ---

    async def is_token_seen(self, chain: str, address: str) -> bool:
        cur = await self.conn.execute(
            "SELECT 1 FROM seen_tokens WHERE chain=? AND address=?",
            (chain, address.lower()),
        )
        row = await cur.fetchone()
        return row is not None

    async def mark_token_seen(self, chain: str, address: str) -> None:
        await self.conn.execute(
            "INSERT OR IGNORE INTO seen_tokens(chain, address, first_seen_at) VALUES(?,?,?)",
            (chain, address.lower(), _utc_now()),
        )
        await self.conn.commit()

    # --- alert pair dedupe ---

    async def has_alert_pair(self, chain: str, token_address: str, reason: str) -> bool:
        cur = await self.conn.execute(
            "SELECT 1 FROM alert_pairs WHERE chain=? AND token_address=? AND reason=?",
            (chain, token_address.lower(), reason),
        )
        return (await cur.fetchone()) is not None

    async def mark_alert_pair(self, chain: str, token_address: str, reason: str) -> None:
        await self.conn.execute(
            "INSERT OR IGNORE INTO alert_pairs(chain, token_address, reason, created_at) "
            "VALUES(?,?,?,?)",
            (chain, token_address.lower(), reason, _utc_now()),
        )
        await self.conn.commit()

    # --- entity alert counts / blacklist ---

    async def get_entity(self, entity_type: str, entity_key: str) -> EntityAlertState:
        key = entity_key.lower() if entity_type == "dev" else entity_key.lstrip("@").lower()
        cur = await self.conn.execute(
            "SELECT entity_type, entity_key, alert_count, blacklisted "
            "FROM entity_alerts WHERE entity_type=? AND entity_key=?",
            (entity_type, key),
        )
        row = await cur.fetchone()
        if row is None:
            return EntityAlertState(entity_type, key, 0, False)
        return EntityAlertState(
            entity_type=row["entity_type"],
            entity_key=row["entity_key"],
            alert_count=int(row["alert_count"]),
            blacklisted=bool(row["blacklisted"]),
        )

    async def is_blacklisted(self, entity_type: str, entity_key: str) -> bool:
        state = await self.get_entity(entity_type, entity_key)
        return state.blacklisted

    async def increment_entity_alert(
        self,
        entity_type: str,
        entity_key: str,
        *,
        limit: int,
    ) -> EntityAlertState:
        """Increment alert count; auto-blacklist when count reaches limit."""
        key = entity_key.lower() if entity_type == "dev" else entity_key.lstrip("@").lower()
        now = _utc_now()
        cur = await self.conn.execute(
            "SELECT alert_count, blacklisted FROM entity_alerts "
            "WHERE entity_type=? AND entity_key=?",
            (entity_type, key),
        )
        row = await cur.fetchone()
        if row is None:
            count = 1
            blacklisted = 1 if count >= limit else 0
            await self.conn.execute(
                "INSERT INTO entity_alerts"
                "(entity_type, entity_key, alert_count, blacklisted, blacklisted_at, updated_at) "
                "VALUES(?,?,?,?,?,?)",
                (
                    entity_type,
                    key,
                    count,
                    blacklisted,
                    now if blacklisted else None,
                    now,
                ),
            )
        else:
            if row["blacklisted"]:
                await self.conn.commit()
                return EntityAlertState(entity_type, key, int(row["alert_count"]), True)
            count = int(row["alert_count"]) + 1
            blacklisted = 1 if count >= limit else 0
            await self.conn.execute(
                "UPDATE entity_alerts SET alert_count=?, blacklisted=?, "
                "blacklisted_at=CASE WHEN ?=1 THEN ? ELSE blacklisted_at END, updated_at=? "
                "WHERE entity_type=? AND entity_key=?",
                (count, blacklisted, blacklisted, now, now, entity_type, key),
            )
        await self.conn.commit()
        return EntityAlertState(entity_type, key, count, bool(blacklisted))

    async def force_blacklist(self, entity_type: str, entity_key: str) -> None:
        key = entity_key.lower() if entity_type == "dev" else entity_key.lstrip("@").lower()
        now = _utc_now()
        await self.conn.execute(
            "INSERT INTO entity_alerts"
            "(entity_type, entity_key, alert_count, blacklisted, blacklisted_at, updated_at) "
            "VALUES(?,?,?,?,?,?) "
            "ON CONFLICT(entity_type, entity_key) DO UPDATE SET "
            "blacklisted=1, blacklisted_at=excluded.blacklisted_at, updated_at=excluded.updated_at",
            (entity_type, key, 999, 1, now, now),
        )
        await self.conn.commit()

    async def list_blacklist(self, limit: int = 50) -> list[EntityAlertState]:
        cur = await self.conn.execute(
            "SELECT entity_type, entity_key, alert_count, blacklisted "
            "FROM entity_alerts WHERE blacklisted=1 "
            "ORDER BY blacklisted_at DESC LIMIT ?",
            (limit,),
        )
        rows = await cur.fetchall()
        return [
            EntityAlertState(
                entity_type=r["entity_type"],
                entity_key=r["entity_key"],
                alert_count=int(r["alert_count"]),
                blacklisted=True,
            )
            for r in rows
        ]

    # --- subscribers ---

    async def add_subscriber(self, chat_id: int) -> None:
        now = _utc_now()
        await self.conn.execute(
            "INSERT INTO subscribers(chat_id, active, created_at, updated_at) VALUES(?,?,?,?) "
            "ON CONFLICT(chat_id) DO UPDATE SET active=1, updated_at=excluded.updated_at",
            (chat_id, 1, now, now),
        )
        await self.conn.commit()

    async def remove_subscriber(self, chat_id: int) -> None:
        now = _utc_now()
        await self.conn.execute(
            "UPDATE subscribers SET active=0, updated_at=? WHERE chat_id=?",
            (now, chat_id),
        )
        await self.conn.commit()

    async def list_active_subscribers(self) -> list[int]:
        cur = await self.conn.execute(
            "SELECT chat_id FROM subscribers WHERE active=1"
        )
        rows = await cur.fetchall()
        return [int(r["chat_id"]) for r in rows]

    # --- bot state ---

    async def set_state(self, key: str, value: Any) -> None:
        payload = json.dumps(value)
        await self.conn.execute(
            "INSERT INTO bot_state(key, value, updated_at) VALUES(?,?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
            (key, payload, _utc_now()),
        )
        await self.conn.commit()

    async def get_state(self, key: str, default: Any = None) -> Any:
        cur = await self.conn.execute(
            "SELECT value FROM bot_state WHERE key=?", (key,)
        )
        row = await cur.fetchone()
        if row is None:
            return default
        try:
            return json.loads(row["value"])
        except json.JSONDecodeError:
            return default

    async def stats(self) -> dict[str, int]:
        async def _count(sql: str) -> int:
            cur = await self.conn.execute(sql)
            row = await cur.fetchone()
            return int(row[0]) if row else 0

        return {
            "seen_tokens": await _count("SELECT COUNT(*) FROM seen_tokens"),
            "alert_pairs": await _count("SELECT COUNT(*) FROM alert_pairs"),
            "blacklisted": await _count(
                "SELECT COUNT(*) FROM entity_alerts WHERE blacklisted=1"
            ),
            "subscribers": await _count(
                "SELECT COUNT(*) FROM subscribers WHERE active=1"
            ),
        }
