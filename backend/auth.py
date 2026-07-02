"""Optional API key authentication with multi-tenant context."""

from __future__ import annotations

from fastapi import Header, HTTPException, Query, WebSocket

from backend.config import settings
from backend.models.auth import DEFAULT_TENANT_ID, AuthContext, Role


async def get_auth_context(
    x_api_key: str | None = Header(default=None),
    api_key: str | None = Query(default=None),
) -> AuthContext:
    if not settings.api_key:
        return AuthContext(tenant_id=DEFAULT_TENANT_ID, role=Role.ADMIN)

    token = x_api_key or api_key
    if not token:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")

    from backend.platform import platform

    if settings.multi_tenant and platform.tenant_store:
        ctx = await platform.tenant_store.resolve_api_key(token)
        if ctx:
            return ctx

    if settings.api_key and token == settings.api_key:
        return AuthContext(tenant_id=DEFAULT_TENANT_ID, role=Role.ADMIN)

    raise HTTPException(status_code=401, detail="Invalid or missing API key")


async def verify_api_key(
    x_api_key: str | None = Header(default=None),
    api_key: str | None = Query(default=None),
) -> None:
    await get_auth_context(x_api_key=x_api_key, api_key=api_key)


async def verify_ws_api_key(websocket: WebSocket) -> AuthContext | None:
    if not settings.api_key:
        return AuthContext(tenant_id=DEFAULT_TENANT_ID, role=Role.ADMIN)
    key = websocket.headers.get("x-api-key") or websocket.query_params.get("api_key")
    if not key:
        return None
    from backend.platform import platform

    if settings.multi_tenant and platform.tenant_store:
        ctx = await platform.tenant_store.resolve_api_key(key)
        if ctx:
            return ctx
    if settings.api_key and key == settings.api_key:
        return AuthContext(tenant_id=DEFAULT_TENANT_ID, role=Role.ADMIN)
    return None
