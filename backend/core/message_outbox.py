"""Message outbox — persist pending deliveries for ACK and retry."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

import aiosqlite

from backend.config import settings
from backend.models.message import Message

logger = logging.getLogger(__name__)


class MessageOutbox:
    def __init__(self, db_path: str | None = None) -> None:
        self._db_path = db_path or settings.tasks_db_path
        self._db: aiosqlite.Connection | None = None

    async def connect(self) -> None:
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        self._db = await aiosqlite.connect(self._db_path)
        await self._db.execute(
            """
            CREATE TABLE IF NOT EXISTS message_outbox (
                message_id TEXT PRIMARY KEY,
                channel TEXT NOT NULL,
                message_json TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                retries INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            )
            """
        )
        await self._db.commit()

    async def disconnect(self) -> None:
        if self._db:
            await self._db.close()

    async def enqueue(self, message: Message, channel: str) -> None:
        assert self._db is not None
        await self._db.execute(
            """
            INSERT OR IGNORE INTO message_outbox
            (message_id, channel, message_json, status, retries, created_at)
            VALUES (?, ?, ?, 'pending', 0, ?)
            """,
            (message.id, channel, message.model_dump_json(), datetime.now(timezone.utc).isoformat()),
        )
        await self._db.commit()

    async def ack(self, message_id: str) -> None:
        assert self._db is not None
        await self._db.execute(
            "UPDATE message_outbox SET status = 'acked' WHERE message_id = ?",
            (message_id,),
        )
        await self._db.commit()

    async def pending_for_channel(self, channel: str) -> list[Message]:
        assert self._db is not None
        async with self._db.execute(
            "SELECT message_json FROM message_outbox WHERE channel = ? AND status = 'pending'",
            (channel,),
        ) as cursor:
            rows = await cursor.fetchall()
        return [Message.model_validate_json(row[0]) for row in rows]

    async def list_retryable(self, max_retries: int, grace_seconds: int = 60) -> list[Message]:
        assert self._db is not None
        from datetime import timedelta

        cutoff = (datetime.now(timezone.utc) - timedelta(seconds=grace_seconds)).isoformat()
        async with self._db.execute(
            """
            SELECT message_json FROM message_outbox
            WHERE status = 'pending' AND retries < ?
              AND (retries > 0 OR created_at < ?)
            ORDER BY created_at
            LIMIT 50
            """,
            (max_retries, cutoff),
        ) as cursor:
            rows = await cursor.fetchall()
        return [Message.model_validate_json(row[0]) for row in rows]

    async def increment_retry(self, message_id: str) -> int:
        assert self._db is not None
        await self._db.execute(
            "UPDATE message_outbox SET retries = retries + 1 WHERE message_id = ?",
            (message_id,),
        )
        await self._db.commit()
        async with self._db.execute(
            "SELECT retries FROM message_outbox WHERE message_id = ?", (message_id,)
        ) as cursor:
            row = await cursor.fetchone()
        return row[0] if row else 0

    async def mark_failed(self, message_id: str) -> None:
        assert self._db is not None
        await self._db.execute(
            "UPDATE message_outbox SET status = 'failed' WHERE message_id = ?",
            (message_id,),
        )
        await self._db.commit()

    async def stats(self) -> dict[str, int]:
        assert self._db is not None
        counts: dict[str, int] = {}
        async with self._db.execute(
            "SELECT status, COUNT(*) FROM message_outbox GROUP BY status"
        ) as cursor:
            rows = await cursor.fetchall()
        for status, count in rows:
            counts[status] = count
        return counts

    async def list_failed(self, limit: int = 50) -> list[Message]:
        assert self._db is not None
        async with self._db.execute(
            "SELECT message_json FROM message_outbox WHERE status = 'failed' ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ) as cursor:
            rows = await cursor.fetchall()
        return [Message.model_validate_json(row[0]) for row in rows]

    async def reset_for_retry(self, message_id: str) -> bool:
        assert self._db is not None
        cursor = await self._db.execute(
            """
            UPDATE message_outbox SET status = 'pending', retries = 0
            WHERE message_id = ? AND status = 'failed'
            """,
            (message_id,),
        )
        await self._db.commit()
        return cursor.rowcount > 0

    async def get_pending_message(self, message_id: str) -> tuple[Message, str] | None:
        assert self._db is not None
        async with self._db.execute(
            "SELECT message_json, channel FROM message_outbox WHERE message_id = ? AND status = 'pending'",
            (message_id,),
        ) as cursor:
            row = await cursor.fetchone()
        if not row:
            return None
        return Message.model_validate_json(row[0]), row[1]

    async def purge_failed(self) -> int:
        """Delete all failed outbox entries. Returns number of rows removed."""
        assert self._db is not None
        cursor = await self._db.execute("DELETE FROM message_outbox WHERE status = 'failed'")
        await self._db.commit()
        return cursor.rowcount or 0
