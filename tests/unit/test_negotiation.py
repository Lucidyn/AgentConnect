"""Negotiation protocol unit tests."""

from __future__ import annotations

import pytest

from backend.core.negotiation import run_negotiation_round, unresolved_questions
from backend.models.plan import AssignmentStatus, TaskAssignment, TaskPlan
from backend.models.task_context import NegotiationState, TaskContext


class _FakePlanner:
    def __init__(self):
        self.sent = []

    async def send(self, to_agent, content, metadata=None, **kwargs):
        self.sent.append((to_agent, content, metadata))


class _FakeOrchestrator:
    def __init__(self):
        self._planner = _FakePlanner()
        self.task_id = "t-1"


@pytest.mark.asyncio
async def test_negotiation_round_resolves_question():
    plan = TaskPlan(
        summary="s",
        assignments=[
            TaskAssignment(
                id="t1",
                agent="Research",
                task="r",
                depends_on=[],
                status=AssignmentStatus.DONE,
            ),
            TaskAssignment(id="t2", agent="Writer", task="w", depends_on=["t1"]),
        ],
    )
    ctx = TaskContext(
        collaboration_mode="blackboard",
        negotiation=True,
        negotiation_state=NegotiationState(max_rounds=2),
        results={"t1": "调研发现 A、B、C"},
    )
    ctx.workspace.open_questions.append("目标读者是谁？")

    orch = _FakeOrchestrator()
    progressed = await run_negotiation_round(orch, plan, ctx, plan.assignments[1])
    assert progressed is True
    assert ctx.negotiation_state.round == 1
    assert len(ctx.negotiation_state.resolved) == 1
    assert unresolved_questions(ctx) == []
    assert orch._planner.sent
