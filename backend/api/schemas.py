"""HTTP request/response schemas."""

from pydantic import BaseModel


class TaskRequest(BaseModel):
    task: str


class TaskResponse(BaseModel):
    task_id: str
    message_id: str
    status: str
    task: str


class MemoryQueryRequest(BaseModel):
    query: str
    limit: int = 5
    task_id: str = ""


class ApprovalRequest(BaseModel):
    action: str  # approve | reject | retry
