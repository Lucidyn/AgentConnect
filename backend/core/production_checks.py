"""Startup checks for production deployments."""

from __future__ import annotations

import logging

from backend.config import settings

logger = logging.getLogger(__name__)


def collect_production_warnings() -> list[str]:
    warnings: list[str] = []
    if settings.production_mode and not settings.api_key:
        warnings.append("PRODUCTION_MODE=true but API_KEY is not set — refusing open admin access")
    elif not settings.api_key:
        warnings.append("API_KEY is not set — all API routes run in open admin mode (dev only)")
    if settings.production_mode and settings.use_qdrant and not settings.database_url:
        warnings.append(
            "PRODUCTION_MODE with local Qdrant and SQLite — set USE_QDRANT=false or use external Qdrant for multi-process"
        )
    if settings.api_key and len(settings.api_key) < 16:
        warnings.append("API_KEY is shorter than 16 characters — use a longer random secret")
    return warnings


def log_production_warnings() -> None:
    warnings = collect_production_warnings()
    for message in warnings:
        logger.warning("[production-check] %s", message)
