"""Per-task runtime context — isolated from Agent in-memory state."""

from __future__ import annotations

from pydantic import BaseModel

from backend.models.plan import TaskAssignment, TaskPlan


class LoopState(BaseModel):
    iteration: int = 0
    max_iterations: int = 3
    feedback: str = ""
    status: str = "running"  # running | passed | failed


class WorkspaceState(BaseModel):
    facts: list[str] = []
    decisions: list[str] = []
    open_questions: list[str] = []
    blockers: list[str] = []
    artifacts: list[str] = []


class TaskContext(BaseModel):
    research_result: str = ""
    coder_result: str = ""
    vision_result: str = ""
    results: dict[str, str] = {}
    approval_message: str = ""
    approval_assignment_id: str = ""
    processed_message_ids: list[str] = []
    assignment_retries: dict[str, int] = {}
    retry_feedback: str = ""
    loops: dict[str, LoopState] = {}
    workspace: WorkspaceState = WorkspaceState()

    @staticmethod
    def plan_from_record(plan_data: dict | None) -> TaskPlan | None:
        if not plan_data:
            return None
        return TaskPlan(
            summary=plan_data.get("summary", ""),
            steps=plan_data.get("steps", []),
            assignments=[
                TaskAssignment.model_validate(a) for a in plan_data.get("assignments", [])
            ],
        )
