"""Message outbox — persist pending deliveries for ACK and retry."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from backend.config import settings
from backend.core.db.base import Database, create_database
from backend.core.db.schema import init_schema
from backend.models.message import Message

logger = logging.getLogger(__name__)


class MessageOutbox:
    def __init__(self, db_or_path: Database | str | None = None) -> None:
        if isinstance(db_or_path, Database):
            self._db = db_or_path
            self._db_path: str | None = None
            self._owns_db = False
        else:
            self._db = None
            self._db_path = db_or_path or settings.tasks_db_path
            self._owns_db = False

    async def connect(self) -> None:
        if self._db is None:
            self._db = await create_database(sqlite_path=self._db_path)
            self._owns_db = True
        await init_schema(self._db)

    async def disconnect(self) -> None:
        if self._owns_db and self._db:
            await self._db.disconnect()
        self._db = None
        self._owns_db = False

    def _ts(self) -> Any:
        now = datetime.now(timezone.utc)
        if self._db and self._db.is_postgres:
            return now
        return now.isoformat()

    def _enqueue_sql(self) -> str:
        if self._db and self._db.is_postgres:
            return """
            INSERT INTO message_outbox
            (message_id, channel, message_json, status, retries, created_at)
            VALUES (?, ?, ?, 'pending', 0, ?)
            ON CONFLICT (message_id) DO NOTHING
            """
        return """
            INSERT OR IGNORE INTO message_outbox
            (message_id, channel, message_json, status, retries, created_at)
            VALUES (?, ?, ?, 'pending', 0, ?)
            """

    async def enqueue(self, message: Message, channel: str) -> None:
        assert self._db is not None
        await self._db.execute(
            self._enqueue_sql(),
            (message.id, channel, message.model_dump_json(), self._ts()),
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
        rows = await self._db.fetchall(
            "SELECT message_json FROM message_outbox WHERE channel = ? AND status = 'pending'",
            (channel,),
        )
        return [Message.model_validate_json(row[0]) for row in rows]

    async def list_retryable(self, max_retries: int, grace_seconds: int = 60) -> list[Message]:
        assert self._db is not None
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=grace_seconds)
        cutoff_val = cutoff if self._db.is_postgres else cutoff.isoformat()
        rows = await self._db.fetchall(
            """
            SELECT message_json FROM message_outbox
            WHERE status = 'pending' AND retries < ?
              AND (retries > 0 OR created_at < ?)
            ORDER BY created_at
            LIMIT 50
            """,
            (max_retries, cutoff_val),
        )
        return [Message.model_validate_json(row[0]) for row in rows]

    async def increment_retry(self, message_id: str) -> int:
        assert self._db is not None
        await self._db.execute(
            "UPDATE message_outbox SET retries = retries + 1 WHERE message_id = ?",
            (message_id,),
        )
        await self._db.commit()
        row = await self._db.fetchone(
            "SELECT retries FROM message_outbox WHERE message_id = ?",
            (message_id,),
        )
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
        rows = await self._db.fetchall(
            "SELECT status, COUNT(*) FROM message_outbox GROUP BY status"
        )
        return {status: count for status, count in rows}

    async def list_failed(self, limit: int = 50) -> list[Message]:
        assert self._db is not None
        rows = await self._db.fetchall(
            "SELECT message_json FROM message_outbox WHERE status = 'failed' ORDER BY created_at DESC LIMIT ?",
            (limit,),
        )
        return [Message.model_validate_json(row[0]) for row in rows]

    async def reset_for_retry(self, message_id: str) -> bool:
        assert self._db is not None
        count = await self._db.execute(
            """
            UPDATE message_outbox SET status = 'pending', retries = 0
            WHERE message_id = ? AND status = 'failed'
            """,
            (message_id,),
        )
        await self._db.commit()
        return count > 0

    async def get_pending_message(self, message_id: str) -> tuple[Message, str] | None:
        assert self._db is not None
        row = await self._db.fetchone(
            "SELECT message_json, channel FROM message_outbox WHERE message_id = ? AND status = 'pending'",
            (message_id,),
        )
        if not row:
            return None
        return Message.model_validate_json(row[0]), row[1]

    async def purge_failed(self) -> int:
        """Delete all failed outbox entries. Returns number of rows removed."""
        assert self._db is not None
        count = await self._db.execute("DELETE FROM message_outbox WHERE status = 'failed'")
        await self._db.commit()
        return count
