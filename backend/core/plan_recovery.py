"""Recover in-flight plan assignments after process restart."""

from __future__ import annotations

import logging

from backend.models.plan import TaskPlan

logger = logging.getLogger(__name__)


async def recover_plan_assignments(task_store, task_id: str) -> int:
    """Reset RUNNING sub-assignments so dispatch can resume after restart."""
    task = await task_store.get(task_id)
    if not task or not task.plan:
        return 0
    plan = TaskPlan.from_record(task.plan)
    if not plan:
        return 0
    reset = plan.reset_running_to_pending()
    if reset:
        await task_store.save_plan(task_id, plan.to_context())
        logger.info("Reset %d RUNNING assignment(s) for task %s", reset, task_id)
    return reset
