from enum import Enum
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


class MessageType(str, Enum):
    TASK = "task"
    RESPONSE = "response"
    BROADCAST = "broadcast"
    STATUS = "status"
    ERROR = "error"


class Message(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    task_id: str = ""
    trace_id: str = ""
    from_agent: str
    to_agent: str
    content: str
    message_type: MessageType = MessageType.TASK
    metadata: dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def with_trace(self) -> "Message":
        if not self.trace_id:
            self.trace_id = self.task_id or self.id
        return self

    def channel_for_recipient(self) -> str:
        return f"agent/{self.to_agent}"

    def to_json(self) -> str:
        return self.model_dump_json()

    @classmethod
    def from_json(cls, data: str) -> "Message":
        return cls.model_validate_json(data)


class AgentInfo(BaseModel):
    name: str
    role: str
    capabilities: list[str]
    description: str = ""
    status: str = "idle"
    registered_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
