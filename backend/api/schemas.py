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


class SaveTemplateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=80)
    description: str = Field(default="", max_length=240)
    custom_plan: dict


class ResumeTaskRequest(BaseModel):
    from_assignment: str = Field(default="", max_length=64)


class ReplayTaskRequest(BaseModel):
    checkpoint_id: str = Field(default="", max_length=64)
    from_assignment: str = Field(default="", max_length=64)


class ImportTemplateRequest(BaseModel):
    template: dict


class TenantBudgetRequest(BaseModel):
    budget_usd: float = Field(ge=0)


class TaskResponse(BaseModel):
    task_id: str
    message_id: str
    status: str
    task: str
    queue_position: int = 0
    estimated_wait_seconds: int = 0


class MemoryQueryRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=2000)
    limit: int = Field(default=5, ge=1, le=50)
    task_id: str = Field(default="", max_length=64)


class ApprovalRequest(BaseModel):
    action: Literal["approve", "reject", "retry"]


class CreateTenantRequest(BaseModel):
    tenant_id: str = Field(..., min_length=1, max_length=64, pattern=r"^[a-zA-Z0-9_-]+$")
    name: str = Field(..., min_length=1, max_length=120)


class CreateApiKeyRequest(BaseModel):
    name: str = Field(default="", max_length=80)
    role: Literal["viewer", "operator", "admin"] = "operator"


class A2ATaskSendRequest(BaseModel):
    id: str = Field(default="", max_length=64)
    message: dict = Field(default_factory=dict)


class A2AJsonRpcRequest(BaseModel):
    jsonrpc: str = "2.0"
    id: str | int | None = None
    method: str
    params: dict = Field(default_factory=dict)
