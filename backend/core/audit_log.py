"""Immutable audit trail for tenant actions."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from backend.core.db.base import Database

logger = logging.getLogger(__name__)

AUDIT_DDL = """
CREATE TABLE IF NOT EXISTS audit_logs (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    actor TEXT NOT NULL,
    action TEXT NOT NULL,
    task_id TEXT DEFAULT '',
    detail_json TEXT DEFAULT '{}',
    created_at TEXT NOT NULL
);
"""


class AuditLog:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def ensure_schema(self) -> None:
        await self._db.execute(AUDIT_DDL)
        await self._db.execute(
            "CREATE INDEX IF NOT EXISTS idx_audit_tenant_created "
            "ON audit_logs(tenant_id, created_at)"
        )
        await self._db.commit()

    async def record(
        self,
        *,
        tenant_id: str,
        actor: str,
        action: str,
        task_id: str = "",
        detail: dict[str, Any] | None = None,
    ) -> None:
        await self._db.execute(
            """
            INSERT INTO audit_logs (id, tenant_id, actor, action, task_id, detail_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(uuid4()),
                tenant_id,
                actor,
                action,
                task_id,
                json.dumps(detail or {}, ensure_ascii=False),
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        await self._db.commit()

    async def list_for_tenant(
        self, tenant_id: str, *, limit: int = 50, task_id: str = ""
    ) -> list[dict[str, Any]]:
        if task_id:
            rows = await self._db.fetchall(
                """
                SELECT id, tenant_id, actor, action, task_id, detail_json, created_at
                FROM audit_logs
                WHERE tenant_id = ? AND task_id = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (tenant_id, task_id, limit),
            )
        else:
            rows = await self._db.fetchall(
                """
                SELECT id, tenant_id, actor, action, task_id, detail_json, created_at
                FROM audit_logs
                WHERE tenant_id = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (tenant_id, limit),
            )
        items: list[dict[str, Any]] = []
        for row in rows:
            detail = {}
            try:
                detail = json.loads(row[5] or "{}")
            except json.JSONDecodeError:
                pass
            items.append(
                {
                    "id": row[0],
                    "tenant_id": row[1],
                    "actor": row[2],
                    "action": row[3],
                    "task_id": row[4],
                    "detail": detail,
                    "created_at": row[6],
                }
            )
        return items
