"""Health, metrics, and index routes."""

from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse, Response

from backend.config import settings
from backend.core.metrics import metrics_response
from backend.core.replica import get_replica_id
from backend.core.runtime import list_runtimes
from backend.platform import platform

router = APIRouter(tags=["health"])

STATIC_DIR = Path(__file__).resolve().parents[2] / "static"


@router.get("/metrics")
async def metrics():
    await platform.refresh_metrics()
    body, content_type = metrics_response()
    return Response(content=body, content_type=content_type)


@router.get("/")
async def index():
    index_file = STATIC_DIR / "index.html"
    if index_file.exists():
        return FileResponse(index_file)
    return {"message": "Agent Connect API", "docs": "/docs"}


@router.get("/health")
async def health():
    running = await platform.task_store.count_active()
    queued = await platform.task_store.count_queued()
    waiting = await platform.task_store.count_waiting_approval()
    outbox_stats = await platform.message_outbox.stats()
    return {
        "status": "ok",
        "agents": len(platform.agents),
        "llm_available": platform.llm.available,
        "llm_provider": platform.llm.provider_name,
        "shared_memory": type(platform.shared_memory).__name__ if platform.shared_memory else None,
        "tools": platform.tools.list_tools(),
        "queue": {
            "running": running,
            "queued": queued,
            "waiting_approval": waiting,
            "active": running,
            "max_concurrent": settings.max_concurrent_tasks,
        },
        "message_outbox": outbox_stats,
        "message_reliability": settings.message_reliability,
        "runtimes": list_runtimes(),
        "agent_runtimes": platform.agent_runtimes,
        "distributed_workers": settings.distributed_workers,
        "remote_agents": sorted(getattr(platform, "_remote_agents", [])),
        "worker_mode": settings.worker_mode,
        "replica_id": get_replica_id(),
        "database": (
            "postgres"
            if getattr(platform, "_database", None) and platform._database.is_postgres
            else "sqlite"
        ),
    }
