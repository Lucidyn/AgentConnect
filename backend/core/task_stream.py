"""Shared task event stream for internal SSE and A2A streaming."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator

from backend.models.task import TaskRecord, TaskStatus
from backend.platform import platform

_TERMINAL = frozenset(
    {TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED}
)


async def build_task_event_payload(task_id: str, tenant_id: str) -> dict | None:
    current = await platform.task_store.get(task_id, tenant_id=tenant_id)
    if not current:
        return None
    payload: dict = {
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
    return payload


async def iter_task_sse_events(
    task_id: str,
    tenant_id: str,
    *,
    poll_interval: float = 1.0,
) -> AsyncIterator[str]:
    last: str | None = None
    while True:
        payload = await build_task_event_payload(task_id, tenant_id)
        if payload is None:
            yield f"data: {json.dumps({'error': 'not found'})}\n\n"
            break
        line = json.dumps(payload, ensure_ascii=False)
        if line != last:
            yield f"data: {line}\n\n"
            last = line
        if payload.get("status") in {s.value for s in _TERMINAL}:
            break
        await asyncio.sleep(poll_interval)


async def iter_a2a_sse_events(
    task_id: str,
    tenant_id: str,
    *,
    poll_interval: float = 1.0,
) -> AsyncIterator[str]:
    from backend.a2a.protocol import task_to_a2a_stream_event

    last: str | None = None
    while True:
        current = await platform.task_store.get(task_id, tenant_id=tenant_id)
        if not current:
            yield f"data: {json.dumps({'error': 'not found'})}\n\n"
            break
        extra = await build_task_event_payload(task_id, tenant_id) or {}
        event = task_to_a2a_stream_event(current, extra=extra)
        line = json.dumps(event, ensure_ascii=False)
        if line != last:
            yield f"data: {line}\n\n"
            last = line
        if current.status in _TERMINAL:
            break
        await asyncio.sleep(poll_interval)
