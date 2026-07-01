"""Unit tests for plan orchestrator helpers and task context."""

from backend.constants import CODER, RESEARCH
from backend.core.plan_orchestrator import is_stale_attempt
from backend.models.message import Message, MessageType
from backend.models.plan import AssignmentStatus, TaskAssignment, TaskPlan
from backend.models.task_context import TaskContext


def test_is_stale_attempt():
    assignment = TaskAssignment(id="t1", agent=CODER, task="x", attempt=2)
    stale = Message(
        from_agent=CODER,
        to_agent="Planner",
        content="old",
        message_type=MessageType.RESPONSE,
        metadata={"attempt": 1},
    )
    fresh = Message(
        from_agent=CODER,
        to_agent="Planner",
        content="new",
        message_type=MessageType.RESPONSE,
        metadata={"attempt": 2},
    )
    assert is_stale_attempt(stale, assignment) is True
    assert is_stale_attempt(fresh, assignment) is False


def test_task_context_record_result_syncs_legacy_fields():
    ctx = TaskContext()
    assignment = TaskAssignment(id="t1", agent=RESEARCH, task="research")
    ctx.record_result(assignment, "facts about API")
    assert ctx.results["t1"] == "facts about API"
    assert ctx.research_result == "facts about API"
    assert ctx.workspace.facts == ["facts about API"]


def test_task_context_coder_output_prefers_results():
    plan = TaskPlan(
        assignments=[
            TaskAssignment(id="t2", agent=CODER, task="code", status=AssignmentStatus.DONE),
        ]
    )
    ctx = TaskContext(coder_result="legacy", results={"t2": "from results"})
    assert ctx.coder_output(plan) == "from results"


def test_task_plan_from_record():
    data = {
        "summary": "pipe",
        "steps": ["a"],
        "assignments": [{"id": "t1", "agent": "Coder", "task": "x", "depends_on": []}],
    }
    plan = TaskPlan.from_record(data)
    assert plan is not None
    assert plan.summary == "pipe"
    assert plan.assignments[0].agent == "Coder"
