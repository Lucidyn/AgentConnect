"""Aggregate API routers."""

from fastapi import APIRouter

from backend.api.routes import admin, agents, audit, auth_routes, health, messages, system, tasks, templates
from backend.a2a.routes import router as a2a_router

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(auth_routes.router)
api_router.include_router(agents.router)
api_router.include_router(templates.router)
api_router.include_router(tasks.router)
api_router.include_router(messages.router)
api_router.include_router(system.router)
api_router.include_router(admin.router)
api_router.include_router(audit.router)
api_router.include_router(a2a_router)
