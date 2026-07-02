"""Audit log API routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from backend.api.deps import clamp_limit, require_role
from backend.models.auth import AuthContext, Role
from backend.platform import platform

router = APIRouter(prefix="/audit", tags=["audit"])


@router.get("")
async def list_audit_logs(
    task_id: str = "",
    limit: int = 50,
    auth: AuthContext = Depends(require_role(Role.VIEWER)),
):
    if not platform.audit_log:
        return {"entries": []}
    entries = await platform.audit_log.list_for_tenant(
        auth.tenant_id,
        limit=clamp_limit(limit),
        task_id=task_id.strip(),
    )
    return {"entries": entries}
