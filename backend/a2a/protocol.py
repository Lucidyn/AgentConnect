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
