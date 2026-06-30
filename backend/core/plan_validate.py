"""TaskPlan structure validation — DAG integrity checks."""

from __future__ import annotations

from backend.models.plan import TaskAssignment


def validate_assignments(assignments: list[TaskAssignment]) -> list[str]:
    """Return human-readable validation errors; empty list means valid."""
    errors: list[str] = []
    if not assignments:
        errors.append("plan has no assignments")
        return errors

    ids = [a.id for a in assignments]
    seen: set[str] = set()
    for aid in ids:
        if aid in seen:
            errors.append(f"duplicate assignment id: {aid}")
        seen.add(aid)

    id_set = set(ids)
    for assignment in assignments:
        for dep in assignment.depends_on:
            if dep not in id_set:
                errors.append(
                    f"assignment {assignment.id} depends on unknown id: {dep}"
                )

    if _has_cycle(assignments):
        errors.append("dependency cycle detected")

    return errors


def _has_cycle(assignments: list[TaskAssignment]) -> bool:
    graph = {a.id: a.depends_on for a in assignments}
    visited: set[str] = set()
    stack: set[str] = set()

    def dfs(node: str) -> bool:
        if node in stack:
            return True
        if node in visited:
            return False
        stack.add(node)
        for dep in graph.get(node, []):
            if dep in graph and dfs(dep):
                return True
        stack.remove(node)
        visited.add(node)
        return False

    return any(dfs(aid) for aid in graph)
