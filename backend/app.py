"""FastAPI application entry — wiring only."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from backend.api.routes import api_router
from backend.platform import platform

STATIC_DIR = Path(__file__).parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    await platform.start()
    yield
    await platform.stop()


app = FastAPI(
    title="Agent Connect",
    description="Multi-Agent Collaboration Platform",
    version="0.8.0",
    lifespan=lifespan,
)

app.include_router(api_router)

if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
