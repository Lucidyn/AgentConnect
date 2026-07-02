"""External A2A protocol adapter (minimal subset)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request

from backend.api.deps import require_role
from backend.api.schemas import A2ATaskSendRequest
from backend.auth import get_auth_context
from backend.constants import VERSION
from backend.models.auth import AuthContext, Role
from backend.platform import platform

router = APIRouter(prefix="/a2a", tags=["a2a"])


def _extract_user_text(message: dict) -> str:
    parts = message.get("parts") or []
    chunks: list[str] = []
    for part in parts:
        if isinstance(part, dict) and part.get("type") == "text":
            chunks.append(str(part.get("text", "")))
    if chunks:
        return "\n".join(chunk for chunk in chunks if chunk).strip()
    if isinstance(message.get("content"), str):
        return message["content"].strip()
    return ""


@router.get("/agent-card")
async def agent_card(request: Request, _: AuthContext = Depends(get_auth_context)):
    base = str(request.base_url).rstrip("/")
    return {
        "name": "Agent Connect",
        "description": "Multi-agent collaboration platform with planner orchestration.",
        "url": f"{base}/a2a",
        "version": VERSION,
        "capabilities": {
            "streaming": True,
            "tasks": True,
        },
        "skills": [
            {
                "id": "planner-orchestration",
                "name": "Planner Orchestration",
                "description": "Submit a task and receive a multi-agent plan and result.",
            }
        ],
    }


@router.post("/tasks/send")
async def a2a_tasks_send(
    req: A2ATaskSendRequest,
    auth: AuthContext = Depends(require_role(Role.OPERATOR)),
):
    user_text = _extract_user_text(req.message)
    if not user_text:
        raise HTTPException(status_code=400, detail="Message must include text content")

    task, message = await platform.submit_task(
        user_text,
        idempotency_key=req.id,
        tenant_id=auth.tenant_id,
    )
    queue = await platform.task_store.get_queue_info(task.id)
    return {
        "jsonrpc": "2.0",
        "result": {
            "id": task.id,
            "status": {
                "state": task.status.value,
                "message": {
                    "role": "agent",
                    "parts": [{"type": "text", "text": f"Task accepted: {task.id}"}],
                },
            },
            "metadata": {
                "message_id": message.id if message else "",
                "queue_position": queue["queue_position"],
                "estimated_wait_seconds": queue["estimated_wait_seconds"],
            },
        },
    }
