"""Shared FastAPI dependencies."""

from __future__ import annotations

from collections.abc import Callable

from fastapi import Depends, HTTPException, Query

from backend.auth import get_auth_context
from backend.config import settings
from backend.models.auth import AuthContext, Role


def clamp_limit(
    limit: int = Query(default=20, ge=1),
    *,
    maximum: int | None = None,
) -> int:
    cap = maximum or settings.api_max_list_limit
    return min(limit, cap)


def require_role(min_role: Role) -> Callable[..., AuthContext]:
    async def _dep(auth: AuthContext = Depends(get_auth_context)) -> AuthContext:
        if not auth.can(min_role):
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        return auth

    return _dep
