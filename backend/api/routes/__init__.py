"""Aggregate API routers."""

from fastapi import APIRouter

from backend.api.routes import agents, health, messages, system, tasks

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(agents.router)
api_router.include_router(tasks.router)
api_router.include_router(messages.router)
api_router.include_router(system.router)
