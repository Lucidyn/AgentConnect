"""FastAPI application entry — wiring only."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from backend.api.routes import api_router
from backend.config import settings
from backend.constants import VERSION
from backend.core.otel import instrument_fastapi, setup_otel
from backend.core.production_checks import log_production_warnings
from backend.core.rate_limit import RateLimitMiddleware
from backend.platform import platform

STATIC_DIR = Path(__file__).parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    log_production_warnings()
    setup_otel()
    await platform.start()
    yield
    await platform.stop()


app = FastAPI(
    title="Agent Connect",
    description="Multi-Agent Collaboration Platform",
    version=VERSION,
    lifespan=lifespan,
)

if settings.cors_origins.strip():
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[item.strip() for item in settings.cors_origins.split(",") if item.strip()],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

if settings.rate_limit_per_minute > 0:
    app.add_middleware(RateLimitMiddleware, max_per_minute=settings.rate_limit_per_minute)

app.include_router(api_router)
instrument_fastapi(app)

if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
