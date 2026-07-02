"""Optional API key authentication."""

from __future__ import annotations

from fastapi import Header, HTTPException, Query, WebSocket

from backend.config import settings


async def verify_api_key(
    x_api_key: str | None = Header(default=None),
    api_key: str | None = Query(default=None),
) -> None:
    token = x_api_key or api_key
    if settings.api_key and token != settings.api_key:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")


async def verify_ws_api_key(websocket: WebSocket) -> bool:
    if not settings.api_key:
        return True
    key = websocket.headers.get("x-api-key") or websocket.query_params.get("api_key")
    return key == settings.api_key
