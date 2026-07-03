"""Tests for dynamic replan producer selection."""

from backend.core.dynamic_replan import find_replan_producer, try_failure_replan
from backend.models.plan import AssignmentStatus, TaskAssignment, TaskPlan
from backend.models.task_context import TaskContext


def _coding_plan() -> TaskPlan:
    return TaskPlan(
        summary="demo",
        assignments=[
            TaskAssignment(id="t1", agent="Research", task="research", depends_on=[]),
            TaskAssignment(id="t2", agent="Coder", task="code", depends_on=["t1"]),
            TaskAssignment(
                id="t3",
                agent="TestRunner",
                task="test",
                depends_on=["t2"],
            ),
        ],
    )


def test_find_replan_producer_targets_coder_for_test_runner():
    plan = _coding_plan()
    test_asg = plan.find_assignment(assignment_id="t3")
    producer = find_replan_producer(plan, test_asg)
    assert producer is not None
    assert producer.agent == "Coder"
    assert producer.id == "t2"


def test_try_failure_replan_resets_coder_on_test_failure(monkeypatch):
    monkeypatch.setattr("backend.config.settings.dynamic_replan_enabled", True)
    monkeypatch.setattr("backend.config.settings.assignment_max_retries", 2)
    plan = _coding_plan()
    plan.mark_done("t1", agent_name="Research")
    plan.mark_done("t2", agent_name="Coder")
    test_asg = plan.find_assignment(assignment_id="t3")
    test_asg.status = AssignmentStatus.RUNNING
    ctx = TaskContext()

    error = "【测试结果】失败\nFAILED tests/test_app.py::test_health - assert False"
    ok = try_failure_replan(plan, ctx, test_asg, error)
    assert ok is True
    coder = plan.find_assignment(assignment_id="t2")
    assert coder.status == AssignmentStatus.PENDING
    assert ctx.retry_feedback
    assert ctx.last_test_failure_summary
