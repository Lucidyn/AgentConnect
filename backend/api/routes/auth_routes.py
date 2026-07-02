"""Current auth context for clients."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from backend.auth import get_auth_context
from backend.models.auth import AuthContext

router = APIRouter(prefix="/auth", tags=["auth"])


@router.get("/me")
async def auth_me(auth: AuthContext = Depends(get_auth_context)) -> dict:
    return {
        "tenant_id": auth.tenant_id,
        "role": auth.role.value,
        "key_id": auth.key_id,
    }
