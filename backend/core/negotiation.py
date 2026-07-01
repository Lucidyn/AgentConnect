"""Multi-agent negotiation protocol — inline rounds + message intents."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from backend.config import settings
from backend.core.blackboard import post_entry, record_negotiation
from backend.models.message import MessageIntent
from backend.models.plan import AssignmentStatus, TaskAssignment, TaskPlan
from backend.models.task_context import NegotiationState, TaskContext

if TYPE_CHECKING:
    from backend.core.plan_orchestrator import PlanOrchestrator

logger = logging.getLogger(__name__)


def unresolved_questions(ctx: TaskContext) -> list[str]:
    return [
        q for q in ctx.workspace.open_questions if not q.startswith("[resolved]")
    ]


def find_upstream_for_negotiation(
    plan: TaskPlan, assignment: TaskAssignment
) -> TaskAssignment | None:
    for dep_id in reversed(assignment.depends_on):
        dep = plan.find_assignment(assignment_id=dep_id)
        if dep and dep.status == AssignmentStatus.DONE:
            return dep
    return None


async def run_negotiation_round(
    orchestrator: PlanOrchestrator,
    plan: TaskPlan,
    ctx: TaskContext,
    completed: TaskAssignment,
) -> bool:
    """Resolve one round of open questions using upstream context. Returns True if progress."""
    if not ctx.negotiation or ctx.collaboration_mode != "blackboard":
        return False

    state = ctx.negotiation_state
    if state.round >= state.max_rounds:
        return False

    questions = unresolved_questions(ctx)
    if not questions:
        return False

    upstream = find_upstream_for_negotiation(plan, completed)
    if not upstream:
        return False

    question = questions[-1]
    upstream_text = ctx.results.get(upstream.id, "")
    answer = _synthesize_answer(upstream.agent, question, upstream_text)

    post_entry(
        ctx,
        author=upstream.agent,
        content=answer,
        entry_type="decision",
        thread_id=completed.id,
    )
    record_negotiation(
        ctx,
        f"第{state.round + 1}轮 · {upstream.agent} 答复：{answer[:120]}",
    )

    state.round += 1
    state.resolved.append(
        {
            "round": state.round,
            "question": question,
            "answer": answer,
            "from_agent": upstream.agent,
            "to_assignment": completed.id,
        }
    )
    ctx.workspace.open_questions = [
        f"[resolved]{q}" if q == question else q for q in ctx.workspace.open_questions
    ]

    planner = orchestrator._planner
    await planner.send(
        upstream.agent,
        f"协商确认：{question}\n你的答复：{answer}",
        metadata={
            "intent": MessageIntent.NEGOTIATION_DECISION.value,
            "assignment_id": upstream.id,
            "negotiation_round": state.round,
        },
    )
    logger.info(
        "Negotiation round %d for task %s: %s answered %s",
        state.round,
        orchestrator.task_id,
        upstream.agent,
        question[:80],
    )
    return True


def _synthesize_answer(agent: str, question: str, context: str) -> str:
    snippet = context[:400].strip() if context else "（无上游上下文）"
    return f"基于 {agent} 已有产出：{snippet}\n针对「{question[:100]}」请以上游内容为准继续。"


def negotiation_metadata_for_dispatch(ctx: TaskContext) -> dict:
    state = ctx.negotiation_state
    if not state.resolved:
        return {}
    last = state.resolved[-1]
    return {
        "negotiation_round": state.round,
        "last_negotiation_answer": last.get("answer", "")[:200],
    }
