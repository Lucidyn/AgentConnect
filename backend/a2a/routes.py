"""External A2A protocol adapter."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request

from backend.a2a.protocol import a2a_error, a2a_ok, task_to_a2a_status
from backend.api.deps import require_role
from backend.api.schemas import A2AJsonRpcRequest, A2ATaskSendRequest
from backend.auth import get_auth_context
from backend.constants import VERSION
from backend.core.task_stream import iter_a2a_sse_events
from backend.models.auth import AuthContext, Role
from backend.models.task import TaskStatus
from backend.platform import platform

router = APIRouter(prefix="/a2a", tags=["a2a"])

_A2A_NOT_FOUND = -32001
_A2A_INVALID = -32602


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


def _task_id_from_params(params: dict) -> str:
    return str(params.get("id") or params.get("task_id") or "").strip()


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
        "methods": ["tasks/send", "tasks/get", "tasks/cancel", "tasks/stream"],
    }


async def _send_task(
    *,
    user_text: str,
    task_id: str,
    tenant_id: str,
) -> tuple[dict, int]:
    if not user_text:
        return a2a_error(task_id or None, code=_A2A_INVALID, message="Message must include text content"), 400
    task, message = await platform.submit_task(
        user_text,
        idempotency_key=task_id,
        tenant_id=tenant_id,
    )
    queue = await platform.task_store.get_queue_info(task.id)
    return a2a_ok(
        task_id or task.id,
        {
            "id": task.id,
            "status": task_to_a2a_status(task),
            "metadata": {
                "message_id": message.id if message else "",
                "queue_position": queue["queue_position"],
                "estimated_wait_seconds": queue["estimated_wait_seconds"],
            },
        },
    ), 200


async def _get_task(*, task_id: str, tenant_id: str, request_id: str | int | None = None):
    if not task_id:
        return a2a_error(request_id, code=_A2A_INVALID, message="Missing task id"), 400
    task = await platform.task_store.get(task_id, tenant_id=tenant_id)
    if not task:
        return a2a_error(request_id, code=_A2A_NOT_FOUND, message=f"Task '{task_id}' not found"), 404
    queue = await platform.task_store.get_queue_info(task.id)
    return a2a_ok(
        request_id,
        {
            "id": task.id,
            "status": task_to_a2a_status(task),
            "metadata": {
                "queue_position": queue["queue_position"],
                "estimated_wait_seconds": queue["estimated_wait_seconds"],
            },
        },
    ), 200


async def _cancel_task(*, task_id: str, tenant_id: str, request_id: str | int | None = None):
    if not task_id:
        return a2a_error(request_id, code=_A2A_INVALID, message="Missing task id"), 400
    task = await platform.cancel_task(task_id, tenant_id=tenant_id)
    if not task:
        return a2a_error(request_id, code=_A2A_NOT_FOUND, message=f"Task '{task_id}' not found"), 404
    return a2a_ok(request_id, {"id": task.id, "status": task_to_a2a_status(task)}), 200


@router.get("/tasks/{task_id}/stream")
async def a2a_tasks_stream(
    task_id: str,
    auth: AuthContext = Depends(require_role(Role.VIEWER)),
):
    from fastapi.responses import StreamingResponse

    task = await platform.task_store.get(task_id, tenant_id=auth.tenant_id)
    if not task:
        raise HTTPException(status_code=404, detail=f"Task '{task_id}' not found")
    return StreamingResponse(
        iter_a2a_sse_events(task_id, auth.tenant_id),
        media_type="text/event-stream",
    )


@router.post("/tasks/send")
async def a2a_tasks_send(
    req: A2ATaskSendRequest,
    auth: AuthContext = Depends(require_role(Role.OPERATOR)),
):
    body, status = await _send_task(
        user_text=_extract_user_text(req.message),
        task_id=req.id,
        tenant_id=auth.tenant_id,
    )
    if status != 200:
        raise HTTPException(status_code=status, detail=body.get("error", {}).get("message", "A2A error"))
    return body


@router.post("/tasks/get")
async def a2a_tasks_get(
    req: A2ATaskSendRequest,
    auth: AuthContext = Depends(require_role(Role.VIEWER)),
):
    task_id = req.id
    body, status = await _get_task(task_id=task_id, tenant_id=auth.tenant_id, request_id=task_id)
    if status == 404:
        raise HTTPException(status_code=404, detail=body.get("error", {}).get("message", "Not found"))
    return body


@router.post("/tasks/cancel")
async def a2a_tasks_cancel(
    req: A2ATaskSendRequest,
    auth: AuthContext = Depends(require_role(Role.OPERATOR)),
):
    task_id = req.id
    body, status = await _cancel_task(task_id=task_id, tenant_id=auth.tenant_id, request_id=task_id)
    if status == 404:
        raise HTTPException(status_code=404, detail=body.get("error", {}).get("message", "Not found"))
    return body


@router.post("/rpc")
async def a2a_rpc(
    req: A2AJsonRpcRequest,
    auth: AuthContext = Depends(get_auth_context),
):
    method = req.method.strip()
    params = req.params or {}

    if method == "tasks/send":
        auth.require(Role.OPERATOR)
        body, status = await _send_task(
            user_text=_extract_user_text(params.get("message") or {}),
            task_id=str(params.get("id") or ""),
            tenant_id=auth.tenant_id,
        )
    elif method == "tasks/get":
        auth.require(Role.VIEWER)
        body, status = await _get_task(
            task_id=_task_id_from_params(params),
            tenant_id=auth.tenant_id,
            request_id=req.id,
        )
    elif method == "tasks/cancel":
        auth.require(Role.OPERATOR)
        body, status = await _cancel_task(
            task_id=_task_id_from_params(params),
            tenant_id=auth.tenant_id,
            request_id=req.id,
        )
    elif method == "tasks/stream":
        auth.require(Role.VIEWER)
        task_id = _task_id_from_params(params)
        if not task_id:
            body = a2a_error(req.id, code=_A2A_INVALID, message="Missing task id")
            status = 400
        else:
            task = await platform.task_store.get(task_id, tenant_id=auth.tenant_id)
            if not task:
                body = a2a_error(req.id, code=_A2A_NOT_FOUND, message=f"Task '{task_id}' not found")
                status = 404
            else:
                body = a2a_ok(
                    req.id,
                    {
                        "id": task.id,
                        "stream_url": f"/a2a/tasks/{task_id}/stream",
                        "status": task_to_a2a_status(task),
                    },
                )
                status = 200
    else:
        body = a2a_error(req.id, code=-32601, message=f"Method not found: {method}")
        status = 404

    if status >= 400 and "error" not in body:
        raise HTTPException(status_code=status, detail="A2A request failed")
    return body
