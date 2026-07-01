"""Unit tests for task store persistence behavior."""

import pytest

from backend.core.task_store import TaskStore
from backend.models.plan import TaskPlan, TaskAssignment
from backend.models.task import TaskStatus


@pytest.mark.asyncio
async def test_save_plan_does_not_change_task_status(db_path):
    store = TaskStore(db_path)
    await store.connect()
    task = await store.create("status test", status=TaskStatus.WAITING_APPROVAL)
    plan = TaskPlan(
        summary="pipe",
        assignments=[TaskAssignment(id="t1", agent="Coder", task="x")],
    )
    await store.save_plan(task.id, plan.to_context())

    reloaded = await store.get(task.id)
    assert reloaded is not None
    assert reloaded.status == TaskStatus.WAITING_APPROVAL
    assert reloaded.plan is not None

    await store.disconnect()
