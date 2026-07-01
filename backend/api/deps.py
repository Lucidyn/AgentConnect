"""Shared FastAPI dependencies."""

from __future__ import annotations

from fastapi import Query

from backend.config import settings


def clamp_limit(
    limit: int = Query(default=20, ge=1),
    *,
    maximum: int | None = None,
) -> int:
    cap = maximum or settings.api_max_list_limit
    return min(limit, cap)
