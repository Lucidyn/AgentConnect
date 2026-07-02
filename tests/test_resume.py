"""Task resume tests."""

import pytest

from backend.models.plan import AssignmentStatus, TaskPlan


def test_reset_from_assignment():
    plan = TaskPlan.model_validate(
        {
            "summary": "s",
            "assignments": [
                {"id": "t1", "agent": "Research", "task": "a", "depends_on": [], "status": "done"},
                {"id": "t2", "agent": "Writer", "task": "b", "depends_on": ["t1"], "status": "failed"},
            ],
        }
    )
    reset = plan.reset_from_assignment("t2")
    assert reset == ["t2"]
    assert plan.find_assignment(assignment_id="t2").status == AssignmentStatus.PENDING
    assert plan.find_assignment(assignment_id="t1").status == AssignmentStatus.DONE


def test_reset_failed_to_pending():
    plan = TaskPlan.model_validate(
        {
            "summary": "s",
            "assignments": [
                {"id": "t1", "agent": "Research", "task": "a", "depends_on": [], "status": "failed"},
            ],
        }
    )
    assert plan.reset_failed_to_pending() == 1
    assert plan.find_assignment(assignment_id="t1").status == AssignmentStatus.PENDING
