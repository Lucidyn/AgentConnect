"""Phase 3 distributed worker task envelope (Redis Stream / queue)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field


class WorkerTaskEnvelope(BaseModel):
    """Unit of work dispatched to a remote agent worker process."""

    envelope_id: str
    task_id: str
    assignment_id: str
    agent: str
    payload: str
    attempt: int = 1
    trace_id: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class WorkerResultEnvelope(BaseModel):
    envelope_id: str
    task_id: str
    assignment_id: str
    agent: str
    success: bool
    content: str = ""
    error: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)
    completed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
