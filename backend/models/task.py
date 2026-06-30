from enum import Enum
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


class TaskStatus(str, Enum):
    QUEUED = "queued"
    SUBMITTED = "submitted"
    PLANNING = "planning"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    WAITING_APPROVAL = "waiting_approval"


class TaskRecord(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    input: str
    status: TaskStatus = TaskStatus.SUBMITTED
    plan: dict[str, Any] | None = None
    context: dict[str, Any] = Field(default_factory=dict)
    result: str | None = None
    error: str | None = None
    idempotency_key: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
