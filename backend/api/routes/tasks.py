"""Task lifecycle routes."""

from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Depends, Header

from backend.api.schemas import ApprovalRequest, TaskRequest, TaskResponse
from backend.auth import verify_api_key
from backend.models.task import TaskStatus
from backend.platform import platform

router = APIRouter(prefix="/tasks", tags=["tasks"])


@router.get("")
async def list_tasks(limit: int = 20):
    tasks = await platform.task_store.list_tasks(limit=limit)
    return {"tasks": [t.model_dump() for t in tasks]}


@router.get("/result")
async def get_task_result(task_id: str = ""):
    if task_id:
        task = await platform.task_store.get(task_id)
        if not task:
            return {"error": f"Task '{task_id}' not found"}
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
        return {"error": f"Task '{task_id}' not found"}
    return {"task": task.model_dump()}


@router.get("/{task_id}/messages")
async def get_task_messages(task_id: str):
    messages = await platform.task_store.get_messages(task_id)
    return {"task_id": task_id, "messages": [m.model_dump() for m in messages]}


@router.get("/{task_id}/artifacts")
async def get_task_artifacts(task_id: str):
    artifacts = await platform.task_store.list_artifacts(task_id)
    return {"task_id": task_id, "artifacts": [a.model_dump(mode="json") for a in artifacts]}


@router.get("/{task_id}/timeline")
async def get_task_timeline(task_id: str):
    task = await platform.task_store.get(task_id)
    if not task:
        return {"error": f"Task '{task_id}' not found"}
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


@router.get("/{task_id}/stream")
async def stream_task(task_id: str):
    from fastapi.responses import StreamingResponse

    async def events():
        last: str | None = None
        while True:
            task = await platform.task_store.get(task_id)
            if not task:
                yield f"data: {json.dumps({'error': 'not found'})}\n\n"
                break
            payload = {
                "task_id": task_id,
                "status": task.status.value,
                "result": task.result,
            }
            if task.status == TaskStatus.WAITING_APPROVAL:
                payload["approval_message"] = (task.context or {}).get("approval_message", "")
            line = json.dumps(payload, ensure_ascii=False)
            if line != last:
                yield f"data: {line}\n\n"
                last = line
            if task.status in (
                TaskStatus.COMPLETED,
                TaskStatus.FAILED,
                TaskStatus.CANCELLED,
            ):
                break
            await asyncio.sleep(1)

    return StreamingResponse(events(), media_type="text/event-stream")


@router.post("/{task_id}/cancel", dependencies=[Depends(verify_api_key)])
async def cancel_task(task_id: str):
    task = await platform.cancel_task(task_id)
    if not task:
        return {"error": f"Task '{task_id}' not found"}
    return {"task": task.model_dump()}


@router.post("/{task_id}/approve", dependencies=[Depends(verify_api_key)])
async def approve_task(task_id: str, req: ApprovalRequest):
    task = await platform.approve_task(task_id, req.action)
    if not task:
        return {"error": f"Task '{task_id}' not awaiting approval"}
    return {"task": task.model_dump()}


@router.post("", response_model=TaskResponse, dependencies=[Depends(verify_api_key)])
async def submit_task(
    req: TaskRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    task, message = await platform.submit_task(req.task, idempotency_key or "")
    return TaskResponse(
        task_id=task.id,
        message_id=message.id if message else "",
        status=task.status.value,
        task=req.task,
    )
