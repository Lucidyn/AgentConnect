"""Simple in-memory rate limiting middleware."""

from __future__ import annotations

import time
from collections import defaultdict

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from backend.config import settings


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, max_per_minute: int) -> None:
        super().__init__(app)
        self._max = max_per_minute
        self._hits: dict[str, list[float]] = defaultdict(list)

    async def dispatch(self, request: Request, call_next) -> Response:
        if self._max <= 0 or request.url.path in {"/health", "/metrics"}:
            return await call_next(request)

        client = request.headers.get("x-api-key") or request.client.host or "unknown"
        now = time.time()
        window = [t for t in self._hits[client] if now - t < 60]
        if len(window) >= self._max:
            return JSONResponse(
                status_code=429,
                content={"detail": "Rate limit exceeded"},
            )
        window.append(now)
        self._hits[client] = window
        return await call_next(request)


def maybe_rate_limit_middleware():
    if settings.rate_limit_per_minute <= 0:
        return None
    return RateLimitMiddleware
