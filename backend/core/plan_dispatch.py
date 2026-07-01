"""Build dispatch payloads from plan dependencies and task context."""

from __future__ import annotations

from backend.config import settings
from backend.constants import REVIEWER
from backend.core.blackboard import format_blackboard
from backend.models.plan import TaskAssignment, TaskPlan
from backend.models.task_context import TaskContext


def _truncate_context(content: str) -> str:
    limit = settings.assignment_context_max_chars
    if limit <= 0 or len(content) <= limit:
        return content
    return content[:limit] + "\n...(truncated)"


def _transitive_dep_ids(plan: TaskPlan, assignment: TaskAssignment) -> list[str]:
    """Collect upstream dependency ids in execution order."""
    by_id = {item.id: item for item in plan.assignments}
    ordered: list[str] = []
    seen: set[str] = set()

    def visit(dep_id: str) -> None:
        if dep_id in seen:
            return
        dep = by_id.get(dep_id)
        if not dep:
            return
        for upstream in dep.depends_on:
            visit(upstream)
        seen.add(dep_id)
        ordered.append(dep_id)

    for dep_id in assignment.depends_on:
        visit(dep_id)
    return ordered


def build_assignment_task(
    assignment: TaskAssignment,
    plan: TaskPlan,
    ctx: TaskContext,
) -> str:
    """Inject upstream dependency results into the assignment task text."""
    parts: list[str] = []

    for dep_id in _transitive_dep_ids(plan, assignment):
        content = ctx.results.get(dep_id, "")
        if not content:
            continue
        content = _truncate_context(content)
        dep = plan.find_assignment(assignment_id=dep_id)
        label = dep.agent if dep else dep_id
        parts.append(f"[{label}]\n{content}")

    if ctx.retry_feedback and assignment.agent != REVIEWER:
        parts.append(f"修改意见：\n{ctx.retry_feedback}")

    if ctx.collaboration_mode == "blackboard":
        board = format_blackboard(ctx.workspace)
        if board:
            parts.append(board)
        if ctx.negotiation and ctx.workspace.open_questions:
            unresolved = [
                q for q in ctx.workspace.open_questions if not q.startswith("[resolved]")
            ]
            if unresolved:
                parts.append("协商：请回应以下开放问题\n" + "\n".join(f"- {q}" for q in unresolved[-3:]))

    task = assignment.task
    if assignment.agent == REVIEWER and parts:
        task = "请审查以下内容：\n\n" + "\n\n".join(parts)
    elif parts:
        task = f"{task}\n\n" + "\n\n".join(parts)

    return task
