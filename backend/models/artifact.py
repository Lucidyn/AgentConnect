from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


class Artifact(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    task_id: str
    assignment_id: str = ""
    type: str = "text"
    content: Any
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_by: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
