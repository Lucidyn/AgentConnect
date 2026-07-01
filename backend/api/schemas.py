"""HTTP request/response schemas."""

from typing import Literal

from pydantic import BaseModel, Field, field_validator

from backend.config import settings


class TaskRequest(BaseModel):
    task: str = Field(..., min_length=1, max_length=settings.task_input_max_length)
    template_id: str = Field(default="", max_length=64)
    custom_plan: dict | None = None
    collaboration_mode: Literal["", "planner", "blackboard"] = ""
    negotiation: bool | None = None


class ValidatePlanRequest(BaseModel):
    task: str = Field(default="", max_length=settings.task_input_max_length)
    custom_plan: dict


class TaskResponse(BaseModel):
    task_id: str
    message_id: str
    status: str
    task: str


class MemoryQueryRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=2000)
    limit: int = Field(default=5, ge=1, le=50)
    task_id: str = Field(default="", max_length=64)


class ApprovalRequest(BaseModel):
    action: Literal["approve", "reject", "retry"]
