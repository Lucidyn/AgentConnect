"""In-process agent-to-agent query policy."""

from __future__ import annotations

from typing import Any

A2A_MAX_QUERIES = 5

# (from_agent, to_agent) pairs allowed to use ask_agent within a task.
A2A_ALLOWED_PAIRS: frozenset[tuple[str, str]] = frozenset(
    {
        ("Coder", "Research"),
        ("Analyst", "Research"),
        ("Writer", "Research"),
    }
)


def check_a2a_query(from_agent: str, to_agent: str, task_context: dict[str, Any] | None) -> str | None:
    """Return an error message when the query is not allowed, else None."""
    pair = (from_agent, to_agent)
    if pair not in A2A_ALLOWED_PAIRS:
        return f"A2A query from {from_agent} to {to_agent} is not allowed"
    ctx = task_context or {}
    count = int(ctx.get("a2a_query_count", 0))
    if count >= A2A_MAX_QUERIES:
        return f"A2A query limit ({A2A_MAX_QUERIES}) reached for this task"
    return None


def record_a2a_query(task_context: dict[str, Any]) -> dict[str, Any]:
    ctx = dict(task_context or {})
    ctx["a2a_query_count"] = int(ctx.get("a2a_query_count", 0)) + 1
    return ctx
