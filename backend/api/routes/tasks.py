"""Task lifecycle routes."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime

from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import Response

from backend.api.deps import clamp_limit
from backend.api.schemas import ApprovalRequest, ResumeTaskRequest, TaskRequest, TaskResponse
from backend.auth import verify_api_key
from backend.config import settings
from backend.core.llm_usage import estimate_cost, merge_usage
from backend.models.task import TaskStatus
from backend.models.task_context import TaskContext
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


def _workspace_display_entries(task) -> list[dict]:
    """Planner mode stores outputs in context.results; synthesize entries for UI."""
    ctx = task.context or {}
    workspace = ctx.get("workspace", {})
    entries = list(workspace.get("entries") or [])
    if entries:
        return entries

    plan = task.plan or {}
    results = ctx.get("results") or {}
    synthesized: list[dict] = []
    for assignment in plan.get("assignments") or []:
        aid = assignment.get("id", "")
        content = results.get(aid, "")
        if not content:
            continue
        synthesized.append(
            {
                "author": assignment.get("agent", "Agent"),
                "entry_type": "output",
                "content": content,
                "thread_id": aid,
                "created_at": "",
            }
        )
    return synthesized


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


@router.get("/{task_id}/artifacts/{artifact_id}/download")
async def download_task_artifact(task_id: str, artifact_id: str):
    artifact = await platform.task_store.get_artifact(artifact_id)
    if not artifact or artifact.task_id != task_id:
        raise HTTPException(status_code=404, detail=f"Artifact '{artifact_id}' not found")
    if isinstance(artifact.content, (dict, list)):
        body = json.dumps(artifact.content, ensure_ascii=False, indent=2)
        media_type = "application/json"
        ext = "json"
    else:
        body = str(artifact.content)
        media_type = "text/plain; charset=utf-8"
        ext = "txt"
    filename = f"{artifact.type}-{artifact.id[:8]}.{ext}"
    return Response(
        content=body,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/{task_id}/timeline")
async def get_task_timeline(task_id: str):
    task = await platform.task_store.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail=f"Task '{task_id}' not found")
    messages = await platform.task_store.get_messages(task_id)
    ctx = TaskContext.model_validate(task.context or {})
    events = []
    prev_at: datetime | None = None
    for message in messages:
        duration_ms = None
        if prev_at is not None:
            duration_ms = int((message.timestamp - prev_at).total_seconds() * 1000)
        prev_at = message.timestamp
        events.append(
            {
                "at": message.timestamp.isoformat(),
                "from_agent": message.from_agent,
                "to_agent": message.to_agent,
                "type": message.message_type.value,
                "trace_id": message.trace_id,
                "message_id": message.id,
                "assignment_id": message.metadata.get("assignment_id", ""),
                "duration_ms": duration_ms,
            }
        )
    total_duration_ms = None
    if task.created_at and task.updated_at:
        total_duration_ms = int((task.updated_at - task.created_at).total_seconds() * 1000)
    assignment_durations = []
    for assignment_id, started_at in ctx.assignment_started_at.items():
        try:
            started = datetime.fromisoformat(started_at)
        except ValueError:
            continue
        ended = task.updated_at
        for message in reversed(messages):
            if message.metadata.get("assignment_id") == assignment_id:
                ended = message.timestamp
                break
        assignment_durations.append(
            {
                "assignment_id": assignment_id,
                "started_at": started_at,
                "duration_ms": int((ended - started).total_seconds() * 1000),
            }
        )
    return {
        "task_id": task_id,
        "status": task.status.value,
        "created_at": task.created_at.isoformat(),
        "updated_at": task.updated_at.isoformat(),
        "total_duration_ms": total_duration_ms,
        "assignment_durations": assignment_durations,
        "events": events,
    }


@router.get("/{task_id}/usage")
async def get_task_usage(task_id: str):
    task = await platform.task_store.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail=f"Task '{task_id}' not found")
    ctx = TaskContext.model_validate(task.context or {})
    entries = [item.model_dump() for item in ctx.llm_usage]
    totals = merge_usage(ctx.llm_usage)
    cost = estimate_cost(
        totals,
        input_per_1k=settings.llm_cost_input_per_1k,
        output_per_1k=settings.llm_cost_output_per_1k,
    )
    return {
        "task_id": task_id,
        "entries": entries,
        "totals": totals,
        "estimated_cost_usd": round(cost, 6),
    }


@router.get("/{task_id}/workspace")
async def get_task_workspace(task_id: str):
    task = await platform.task_store.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail=f"Task '{task_id}' not found")
    ctx = task.context or {}
    workspace = dict(ctx.get("workspace", {}))
    display_entries = _workspace_display_entries(task)
    if display_entries and not workspace.get("entries"):
        workspace = {**workspace, "entries": display_entries}
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
async def stream_task(task_id: str, _: None = Depends(verify_api_key)):
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
            stream = await platform.stream_buffer.snapshot(task_id)
            payload.update(stream)
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


@router.post("/{task_id}/resume")
async def resume_task(task_id: str, req: ResumeTaskRequest | None = None):
    from_assignment = req.from_assignment if req else ""
    task = await platform.resume_task(task_id, from_assignment=from_assignment)
    if not task:
        raise HTTPException(
            status_code=409,
            detail=f"Task '{task_id}' not found or cannot be resumed",
        )
    return {"task": task.model_dump()}


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
