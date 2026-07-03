"""Dynamic partial replan on assignment failure."""

from __future__ import annotations

from backend.config import settings
from backend.constants import CODER, TEST_RUNNER
from backend.core.pytest_report import extract_test_failure_for_retry
from backend.models.plan import AssignmentStatus, TaskAssignment, TaskPlan
from backend.models.task_context import TaskContext


def find_replan_producer(
    plan: TaskPlan,
    assignment: TaskAssignment,
) -> TaskAssignment | None:
    """Pick upstream producer to reset — TestRunner failures target Coder only."""
    if assignment.agent == TEST_RUNNER:
        coder = plan.find_assignment(agent_name=CODER)
        if coder:
            return coder
    return _find_upstream_producer(plan, assignment)


def try_failure_replan(
    plan: TaskPlan,
    ctx: TaskContext,
    assignment: TaskAssignment,
    error: str,
) -> bool:
    """Reset upstream producer with enriched task text. Returns True if replanned."""
    if not settings.dynamic_replan_enabled:
        return False

    retries = ctx.assignment_retries.get(assignment.id, 0)
    if retries >= settings.assignment_max_retries:
        return False

    producer = find_replan_producer(plan, assignment)
    if not producer:
        return False

    summary = extract_test_failure_for_retry(error) if assignment.agent == TEST_RUNNER else error[:600]

    ctx.assignment_retries[assignment.id] = retries + 1
    producer.task = (
        f"{producer.task}\n\n[自动重规划] 下游 {assignment.agent} 失败，请修正：\n{summary[:800]}"
    )
    producer.status = AssignmentStatus.PENDING
    plan.reset_from_assignment(producer.id)
    ctx.results.pop(producer.id, None)
    ctx.retry_feedback = summary[:1200]
    if assignment.agent == TEST_RUNNER:
        ctx.last_test_failure_summary = summary[:2000]
    return True


def _find_upstream_producer(plan: TaskPlan, assignment: TaskAssignment) -> TaskAssignment | None:
    for dep_id in reversed(assignment.depends_on):
        dep = plan.find_assignment(assignment_id=dep_id)
        if dep and dep.node_type != "human_approval":
            return dep
    for item in reversed(plan.assignments):
        if item.id != assignment.id and item.node_type == "agent":
            return item
    return None
