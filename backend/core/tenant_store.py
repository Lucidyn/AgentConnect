"""Tenant and API key persistence."""

from __future__ import annotations

import hashlib
import logging
import secrets
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from backend.config import settings
from backend.core.db.base import Database
from backend.models.auth import DEFAULT_TENANT_ID, AuthContext, Role

logger = logging.getLogger(__name__)


def hash_api_key(raw: str) -> str:
    salt = settings.api_key_salt or "agent-connect"
    return hashlib.sha256(f"{salt}:{raw}".encode()).hexdigest()


class TenantStore:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def resolve_api_key(self, raw: str) -> AuthContext | None:
        if not raw:
            return None
        row = await self._db.fetchone(
            """
            SELECT id, tenant_id, role FROM api_keys
            WHERE key_hash = ? AND revoked_at IS NULL
            """,
            (hash_api_key(raw),),
        )
        if not row:
            return None
        return AuthContext(tenant_id=row[1], role=Role(row[2]), key_id=row[0])

    async def ensure_default_tenant(self) -> None:
        now = datetime.now(timezone.utc).isoformat()
        existing = await self._db.fetchone(
            "SELECT id FROM tenants WHERE id = ?",
            (DEFAULT_TENANT_ID,),
        )
        if not existing:
            await self._db.execute(
                "INSERT INTO tenants (id, name, created_at) VALUES (?, ?, ?)",
                (DEFAULT_TENANT_ID, "Default", now),
            )
        if settings.api_key:
            await self._ensure_legacy_key(settings.api_key)
        await self._db.commit()

    async def _ensure_legacy_key(self, raw: str) -> None:
        key_hash = hash_api_key(raw)
        row = await self._db.fetchone(
            "SELECT id FROM api_keys WHERE key_hash = ?",
            (key_hash,),
        )
        if row:
            return
        key_id = str(uuid4())
        now = datetime.now(timezone.utc).isoformat()
        await self._db.execute(
            """
            INSERT INTO api_keys (id, tenant_id, key_hash, name, role, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (key_id, DEFAULT_TENANT_ID, key_hash, "legacy-env", Role.ADMIN.value, now),
        )

    async def create_tenant(self, tenant_id: str, name: str) -> dict[str, Any]:
        now = datetime.now(timezone.utc).isoformat()
        await self._db.execute(
            "INSERT INTO tenants (id, name, created_at) VALUES (?, ?, ?)",
            (tenant_id, name, now),
        )
        await self._db.commit()
        return {"id": tenant_id, "name": name, "created_at": now}

    async def get_tenant(self, tenant_id: str) -> dict[str, Any] | None:
        row = await self._db.fetchone(
            "SELECT id, name, created_at FROM tenants WHERE id = ?",
            (tenant_id,),
        )
        if not row:
            return None
        return {"id": row[0], "name": row[1], "created_at": row[2]}

    async def create_api_key(
        self,
        tenant_id: str,
        *,
        name: str = "",
        role: Role = Role.OPERATOR,
    ) -> tuple[str, dict[str, Any]]:
        tenant = await self.get_tenant(tenant_id)
        if not tenant:
            raise ValueError(f"Tenant '{tenant_id}' not found")
        raw = secrets.token_urlsafe(32)
        key_id = str(uuid4())
        now = datetime.now(timezone.utc).isoformat()
        await self._db.execute(
            """
            INSERT INTO api_keys (id, tenant_id, key_hash, name, role, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (key_id, tenant_id, hash_api_key(raw), name or "api-key", role.value, now),
        )
        await self._db.commit()
        return raw, {
            "id": key_id,
            "tenant_id": tenant_id,
            "name": name or "api-key",
            "role": role.value,
            "created_at": now,
        }

    async def list_api_keys(self, tenant_id: str) -> list[dict[str, Any]]:
        rows = await self._db.fetchall(
            """
            SELECT id, tenant_id, name, role, created_at, revoked_at
            FROM api_keys WHERE tenant_id = ?
            ORDER BY created_at DESC
            """,
            (tenant_id,),
        )
        return [
            {
                "id": row[0],
                "tenant_id": row[1],
                "name": row[2],
                "role": row[3],
                "created_at": row[4],
                "revoked": row[5] is not None,
            }
            for row in rows
        ]

    async def revoke_api_key(self, tenant_id: str, key_id: str) -> bool:
        row = await self._db.fetchone(
            """
            SELECT id FROM api_keys
            WHERE id = ? AND tenant_id = ? AND revoked_at IS NULL
            """,
            (key_id, tenant_id),
        )
        if not row:
            return False
        now = datetime.now(timezone.utc).isoformat()
        await self._db.execute(
            "UPDATE api_keys SET revoked_at = ? WHERE id = ?",
            (now, key_id),
        )
        await self._db.commit()
        return True
