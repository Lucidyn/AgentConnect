"""Checkpoint capture and restore for task replay."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from backend.models.checkpoint import CheckpointSnapshot
from backend.models.plan import TaskPlan
from backend.models.task_context import TaskContext


def append_checkpoint(
    ctx: TaskContext,
    plan: TaskPlan,
    assignment_id: str,
    *,
    label: str = "",
) -> CheckpointSnapshot:
    snapshot = CheckpointSnapshot(
        id=str(uuid4())[:8],
        assignment_id=assignment_id,
        label=label or assignment_id,
        created_at=datetime.now(timezone.utc).isoformat(),
        plan=plan.to_context(),
        results=dict(ctx.results),
    )
    ctx.checkpoints.append(snapshot)
    if len(ctx.checkpoints) > 50:
        ctx.checkpoints = ctx.checkpoints[-50:]
    return snapshot


def find_checkpoint(ctx: TaskContext, checkpoint_id: str) -> CheckpointSnapshot | None:
    for item in ctx.checkpoints:
        if item.id == checkpoint_id:
            return item
    return None
