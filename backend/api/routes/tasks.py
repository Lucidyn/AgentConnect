"""Task lifecycle routes."""

from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Depends, Header, HTTPException

from backend.api.deps import clamp_limit
from backend.api.schemas import ApprovalRequest, TaskRequest, TaskResponse
from backend.auth import verify_api_key
from backend.models.task import TaskStatus
from backend.platform import platform

router = APIRouter(prefix="/tasks", tags=["tasks"], dependencies=[Depends(verify_api_key)])


def _task_preview(task) -> str:
    text = (task.input or "")[:80]
    if len(task.input or "") > 80:
        text += "…"
    return text


async def _task_with_queue(task) -> dict:
    data = task.model_dump()
    data["preview"] = _task_preview(task)
    queue = await platform.task_store.get_queue_info(task.id)
    data.update(queue)
    return data


@router.get("")
async def list_tasks(limit: int = Depends(clamp_limit)):
    tasks = await platform.task_store.list_tasks(limit=limit)
    items = []
    for t in tasks:
        items.append(await _task_with_queue(t))
    return {"tasks": items}


@router.get("/result")
async def get_task_result(task_id: str = ""):
    if task_id:
        task = await platform.task_store.get(task_id)
        if not task:
            raise HTTPException(status_code=404, detail=f"Task '{task_id}' not found")
        return {
            "task_id": task.id,
            "status": task.status.value,
            "result": task.result,
            "plan": task.plan,
        }

    for task in await platform.task_store.list_tasks(limit=20):
        if task.status == TaskStatus.COMPLETED:
            return {
                "task_id": task.id,
                "status": task.status.value,
                "result": task.result,
                "plan": task.plan,
            }
    return {"status": "processing", "result": None}


@router.get("/{task_id}")
async def get_task(task_id: str):
    task = await platform.task_store.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail=f"Task '{task_id}' not found")
    return {"task": await _task_with_queue(task)}


@router.get("/{task_id}/messages")
async def get_task_messages(task_id: str):
    task = await platform.task_store.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail=f"Task '{task_id}' not found")
    messages = await platform.task_store.get_messages(task_id)
    return {"task_id": task_id, "messages": [m.model_dump() for m in messages]}


@router.get("/{task_id}/artifacts")
async def get_task_artifacts(task_id: str):
    task = await platform.task_store.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail=f"Task '{task_id}' not found")
    artifacts = await platform.task_store.list_artifacts(task_id)
    return {"task_id": task_id, "artifacts": [a.model_dump(mode="json") for a in artifacts]}


@router.get("/{task_id}/timeline")
async def get_task_timeline(task_id: str):
    task = await platform.task_store.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail=f"Task '{task_id}' not found")
    messages = await platform.task_store.get_messages(task_id)
    events = [
        {
            "at": m.timestamp.isoformat(),
            "from_agent": m.from_agent,
            "to_agent": m.to_agent,
            "type": m.message_type.value,
            "trace_id": m.trace_id,
            "message_id": m.id,
        }
        for m in messages
    ]
    return {
        "task_id": task_id,
        "status": task.status.value,
        "created_at": task.created_at.isoformat(),
        "updated_at": task.updated_at.isoformat(),
        "events": events,
    }


@router.get("/{task_id}/workspace")
async def get_task_workspace(task_id: str):
    task = await platform.task_store.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail=f"Task '{task_id}' not found")
    ctx = task.context or {}
    workspace = ctx.get("workspace", {})
    return {
        "task_id": task_id,
        "template_id": ctx.get("template_id", ""),
        "collaboration_mode": ctx.get("collaboration_mode", "planner"),
        "negotiation": ctx.get("negotiation", False),
        "negotiation_state": ctx.get("negotiation_state", {}),
        "workspace": workspace,
        "plan": task.plan,
    }


@router.get("/{task_id}/stream")
async def stream_task(task_id: str):
    from fastapi.responses import StreamingResponse

    task = await platform.task_store.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail=f"Task '{task_id}' not found")

    async def events():
        last: str | None = None
        while True:
            current = await platform.task_store.get(task_id)
            if not current:
                yield f"data: {json.dumps({'error': 'not found'})}\n\n"
                break
            payload = {
                "task_id": task_id,
                "status": current.status.value,
                "result": current.result,
            }
            queue = await platform.task_store.get_queue_info(task_id)
            payload.update(queue)
            if current.status == TaskStatus.WAITING_APPROVAL:
                payload["approval_message"] = (current.context or {}).get("approval_message", "")
            line = json.dumps(payload, ensure_ascii=False)
            if line != last:
                yield f"data: {line}\n\n"
                last = line
            if current.status in (
                TaskStatus.COMPLETED,
                TaskStatus.FAILED,
                TaskStatus.CANCELLED,
            ):
                break
            await asyncio.sleep(1)

    return StreamingResponse(events(), media_type="text/event-stream")


@router.post("/{task_id}/cancel")
async def cancel_task(task_id: str):
    task = await platform.cancel_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail=f"Task '{task_id}' not found")
    return {"task": task.model_dump()}


@router.post("/{task_id}/approve")
async def approve_task(task_id: str, req: ApprovalRequest):
    task = await platform.approve_task(task_id, req.action)
    if not task:
        raise HTTPException(
            status_code=409,
            detail=f"Task '{task_id}' not found or not awaiting approval",
        )
    return {"task": task.model_dump()}


@router.post("", response_model=TaskResponse)
async def submit_task(
    req: TaskRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    task, message = await platform.submit_task(
        req.task,
        idempotency_key or "",
        template_id=req.template_id,
        custom_plan=req.custom_plan,
        collaboration_mode=req.collaboration_mode,
        negotiation=req.negotiation,
    )
    queue = await platform.task_store.get_queue_info(task.id)
    return TaskResponse(
        task_id=task.id,
        message_id=message.id if message else "",
        status=task.status.value,
        task=req.task,
        queue_position=queue["queue_position"],
        estimated_wait_seconds=queue["estimated_wait_seconds"],
    )
