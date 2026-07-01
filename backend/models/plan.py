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
    attempt: int = 0
    reason: str = ""


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

    def mark_failed(self, assignment_id: str = "", agent_name: str = "") -> TaskAssignment | None:
        if assignment_id:
            for assignment in self.assignments:
                if assignment.id == assignment_id and assignment.status not in (
                    AssignmentStatus.DONE,
                    AssignmentStatus.FAILED,
                ):
                    assignment.status = AssignmentStatus.FAILED
                    return assignment
        if agent_name:
            for assignment in reversed(self.assignments):
                if assignment.agent == agent_name and assignment.status == AssignmentStatus.RUNNING:
                    assignment.status = AssignmentStatus.FAILED
                    return assignment
        return None

    def reset_running_to_pending(self) -> int:
        count = 0
        for assignment in self.assignments:
            if assignment.status == AssignmentStatus.RUNNING:
                assignment.status = AssignmentStatus.PENDING
                count += 1
        return count

    def has_failed(self) -> bool:
        return any(a.status == AssignmentStatus.FAILED for a in self.assignments)

    def find_assignment(
        self, assignment_id: str = "", agent_name: str = ""
    ) -> TaskAssignment | None:
        if assignment_id:
            for assignment in self.assignments:
                if assignment.id == assignment_id:
                    return assignment
        if agent_name:
            for assignment in reversed(self.assignments):
                if assignment.agent == agent_name and assignment.status == AssignmentStatus.RUNNING:
                    return assignment
        return None

    def downstream_ids(self, assignment_id: str) -> set[str]:
        """All assignments that transitively depend on assignment_id."""
        downstream: set[str] = set()
        changed = True
        while changed:
            changed = False
            for assignment in self.assignments:
                if assignment.id in downstream or assignment.id == assignment_id:
                    continue
                if any(
                    dep == assignment_id or dep in downstream for dep in assignment.depends_on
                ):
                    downstream.add(assignment.id)
                    changed = True
        return downstream

    def reset_to_pending(self, assignment_id: str, *, cascade: bool = True) -> list[str]:
        """Reset an assignment (and optionally its downstream) back to pending."""
        reset_ids: list[str] = []
        target = self.find_assignment(assignment_id=assignment_id)
        if not target or target.status not in (
            AssignmentStatus.DONE,
            AssignmentStatus.RUNNING,
        ):
            return reset_ids

        ids_to_reset = {assignment_id}
        if cascade:
            ids_to_reset |= self.downstream_ids(assignment_id)

        for assignment in self.assignments:
            if assignment.id in ids_to_reset and assignment.status in (
                AssignmentStatus.DONE,
                AssignmentStatus.RUNNING,
            ):
                assignment.status = AssignmentStatus.PENDING
                reset_ids.append(assignment.id)
        return reset_ids

    def validate(self) -> list[str]:
        from backend.core.plan_validate import validate_assignments

        return validate_assignments(self.assignments)

    def to_context(self) -> dict[str, Any]:
        return {
            "summary": self.summary,
            "steps": self.steps,
            "assignments": [a.model_dump() for a in self.assignments],
        }
