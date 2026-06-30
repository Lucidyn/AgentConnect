"""Build dispatch payloads from plan dependencies and task context."""

from __future__ import annotations

from backend.constants import REVIEWER
from backend.models.plan import TaskAssignment, TaskPlan
from backend.models.task_context import TaskContext


def build_assignment_task(
    assignment: TaskAssignment,
    plan: TaskPlan,
    ctx: TaskContext,
) -> str:
    """Inject upstream dependency results into the assignment task text."""
    parts: list[str] = []

    for dep_id in assignment.depends_on:
        content = ctx.results.get(dep_id, "")
        if not content:
            continue
        dep = plan.find_assignment(assignment_id=dep_id)
        label = dep.agent if dep else dep_id
        parts.append(f"[{label}]\n{content}")

    if ctx.retry_feedback and assignment.agent != REVIEWER:
        parts.append(f"修改意见：\n{ctx.retry_feedback}")

    task = assignment.task
    if assignment.agent == REVIEWER and parts:
        task = "请审查以下内容：\n\n" + "\n\n".join(parts)
    elif parts:
        task = f"{task}\n\n" + "\n\n".join(parts)

    return task
