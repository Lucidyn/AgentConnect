"""Shared blackboard helpers for multi-agent collaboration."""

from __future__ import annotations

from datetime import datetime, timezone

from backend.models.task_context import BlackboardEntry, TaskContext, WorkspaceState


def format_blackboard(workspace: WorkspaceState, *, limit: int = 8) -> str:
    if not workspace.entries:
        return ""
    lines = ["【协作黑板】"]
    for entry in workspace.entries[-limit:]:
        lines.append(f"- [{entry.author}/{entry.entry_type}] {entry.content[:400]}")
    if workspace.open_questions:
        lines.append("开放问题：" + "；".join(workspace.open_questions[-3:]))
    if workspace.negotiation_log:
        lines.append("协商记录：" + " | ".join(workspace.negotiation_log[-2:]))
    return "\n".join(lines)


def post_entry(
    ctx: TaskContext,
    *,
    author: str,
    content: str,
    entry_type: str = "fact",
    thread_id: str = "",
) -> None:
    ctx.workspace.entries.append(
        BlackboardEntry(
            author=author,
            entry_type=entry_type,
            content=content,
            thread_id=thread_id,
            created_at=datetime.now(timezone.utc),
        )
    )
    if entry_type == "question":
        ctx.workspace.open_questions.append(content[:200])
    elif entry_type == "decision":
        ctx.workspace.decisions.append(content[:200])


def record_negotiation(ctx: TaskContext, message: str) -> None:
    ctx.workspace.negotiation_log.append(message[:300])
