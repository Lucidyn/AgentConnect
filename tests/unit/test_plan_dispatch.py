"""Unit tests for assignment dispatch payload building."""

from backend.core.plan_dispatch import build_assignment_task
from backend.models.plan import AssignmentStatus, TaskAssignment, TaskPlan
from backend.models.task_context import TaskContext


def test_build_assignment_task_injects_dependencies():
    plan = TaskPlan(
        assignments=[
            TaskAssignment(id="t1", agent="Research", task="调研", status=AssignmentStatus.DONE),
            TaskAssignment(
                id="t2", agent="Coder", task="实现", depends_on=["t1"], status=AssignmentStatus.PENDING
            ),
        ]
    )
    ctx = TaskContext(results={"t1": "research output"})
    coder_asg = plan.assignments[1]
    text = build_assignment_task(coder_asg, plan, ctx)
    assert "实现" in text
    assert "[Research]" in text
    assert "research output" in text


def test_build_assignment_task_reviewer_prefix():
    plan = TaskPlan(
        assignments=[
            TaskAssignment(id="t1", agent="Coder", task="code", status=AssignmentStatus.DONE),
            TaskAssignment(
                id="t2", agent="Reviewer", task="审查", depends_on=["t1"], status=AssignmentStatus.PENDING
            ),
        ]
    )
    ctx = TaskContext(results={"t1": "def app(): pass"})
    text = build_assignment_task(plan.assignments[1], plan, ctx)
    assert text.startswith("请审查以下内容")
