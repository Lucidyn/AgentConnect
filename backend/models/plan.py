from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class AssignmentStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


class TaskAssignment(BaseModel):
    id: str
    agent: str
    task: str
    status: AssignmentStatus = AssignmentStatus.PENDING
    depends_on: list[str] = Field(default_factory=list)


class TaskPlan(BaseModel):
    summary: str = ""
    steps: list[str] = Field(default_factory=list)
    assignments: list[TaskAssignment] = Field(default_factory=list)

    def pending_ready(self) -> list[TaskAssignment]:
        done_ids = {a.id for a in self.assignments if a.status == AssignmentStatus.DONE}
        return [
            a
            for a in self.assignments
            if a.status == AssignmentStatus.PENDING
            and all(dep in done_ids for dep in a.depends_on)
        ]

    def all_done(self) -> bool:
        return bool(self.assignments) and all(
            a.status == AssignmentStatus.DONE for a in self.assignments
        )

    def mark_done(self, assignment_id: str = "", agent_name: str = "") -> TaskAssignment | None:
        if assignment_id:
            for assignment in self.assignments:
                if assignment.id == assignment_id and assignment.status != AssignmentStatus.DONE:
                    assignment.status = AssignmentStatus.DONE
                    return assignment
        if agent_name:
            for assignment in reversed(self.assignments):
                if assignment.agent == agent_name and assignment.status == AssignmentStatus.RUNNING:
                    assignment.status = AssignmentStatus.DONE
                    return assignment
        return None

    def to_context(self) -> dict[str, Any]:
        return {
            "summary": self.summary,
            "steps": self.steps,
            "assignments": [a.model_dump() for a in self.assignments],
        }
