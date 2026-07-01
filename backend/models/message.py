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


class MessageIntent(str, Enum):
    ASSIGNMENT_START = "assignment_start"
    ASSIGNMENT_RESULT = "assignment_result"
    ASSIGNMENT_ERROR = "assignment_error"
    RETRY_REQUEST = "retry_request"
    APPROVAL_REQUEST = "approval_request"
    AGENT_QUERY = "agent_query"
    AGENT_ANSWER = "agent_answer"
    NEGOTIATION_QUESTION = "negotiation_question"
    NEGOTIATION_DECISION = "negotiation_decision"
    KNOWLEDGE_SHARE = "knowledge_share"


class Message(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    task_id: str = ""
    trace_id: str = ""
    thread_id: str = ""
    parent_message_id: str = ""
    from_agent: str
    to_agent: str
    content: str
    message_type: MessageType = MessageType.TASK
    metadata: dict[str, Any] = Field(default_factory=dict)
    priority: int = 0
    deadline_at: datetime | None = None
    requires_response: bool = False
    expected_response_type: str = ""
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def with_trace(self) -> "Message":
        if not self.trace_id:
            self.trace_id = self.task_id or self.id
        if not self.thread_id:
            self.thread_id = self.metadata.get("thread_id") or self.task_id or self.trace_id
        if not self.parent_message_id:
            self.parent_message_id = self.metadata.get("reply_to", "")
        return self

    def channel_for_recipient(self) -> str:
        return f"agent/{self.to_agent}"

    def meta(self, key: str, default: Any = None) -> Any:
        return self.metadata.get(key, default)

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
    inputs: list[str] = Field(default_factory=list)
    outputs: list[str] = Field(default_factory=list)
    accepts: list[str] = Field(default_factory=list)
    status: str = "idle"
    registered_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
