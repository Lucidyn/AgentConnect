"""A2A JSON-RPC helpers and task status mapping."""

from __future__ import annotations

from typing import Any

from backend.models.task import TaskRecord, TaskStatus

_TERMINAL = frozenset({TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED})


def a2a_ok(request_id: str | int | None, result: dict[str, Any]) -> dict[str, Any]:
    payload: dict[str, Any] = {"jsonrpc": "2.0", "result": result}
    if request_id is not None:
        payload["id"] = request_id
    return payload


def a2a_error(
    request_id: str | int | None,
    *,
    code: int,
    message: str,
    data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    err: dict[str, Any] = {"code": code, "message": message}
    if data:
        err["data"] = data
    payload: dict[str, Any] = {"jsonrpc": "2.0", "error": err}
    if request_id is not None:
        payload["id"] = request_id
    return payload


def task_to_a2a_status(task: TaskRecord) -> dict[str, Any]:
    state = task.status.value
    if task.status == TaskStatus.WAITING_APPROVAL:
        state = "input-required"
    text = task.result or task.error or f"Task {task.status.value}"
    payload: dict[str, Any] = {
        "state": state,
        "message": {
            "role": "agent",
            "parts": [{"type": "text", "text": text}],
        },
    }
    if task.status in _TERMINAL:
        payload["final"] = True
    return payload


def task_to_a2a_stream_event(task: TaskRecord, *, extra: dict | None = None) -> dict[str, Any]:
    """SSE payload shaped for external A2A consumers."""
    status = task_to_a2a_status(task)
    event: dict[str, Any] = {
        "type": "status-update",
        "task_id": task.id,
        "status": status,
    }
    if extra:
        partial = extra.get("partial_result")
        if partial:
            parts = list(status.get("message", {}).get("parts") or [])
            parts.append({"type": "text", "text": str(partial)})
            status["message"] = {"role": "agent", "parts": parts}
            event["status"] = status
        metadata = {
            key: extra[key]
            for key in (
                "queue_position",
                "estimated_wait_seconds",
                "streaming_agent",
                "streaming_assignment",
            )
            if key in extra and extra[key] is not None
        }
        if metadata:
            event["metadata"] = metadata
    return event
