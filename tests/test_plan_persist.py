"""Plan persistence — guards against dispatch/mark_done race."""

import pytest

from backend.core.task_store import TaskStore
from backend.models.plan import AssignmentStatus, TaskAssignment, TaskPlan
from backend.models.task import TaskStatus
from backend.models.task_context import TaskContext


@pytest.mark.asyncio
async def test_plan_roundtrip_preserves_running_status(db_path):
    store = TaskStore(db_path)
    await store.connect()

    task = await store.create("demo", status=TaskStatus.RUNNING)
    plan = TaskPlan(
        summary="test",
        assignments=[
            TaskAssignment(id="t1", agent="Research", task="a", status=AssignmentStatus.DONE),
            TaskAssignment(
                id="t2", agent="Coder", task="b", status=AssignmentStatus.RUNNING, depends_on=["t1"]
            ),
            TaskAssignment(
                id="t3", agent="Reviewer", task="c", status=AssignmentStatus.PENDING, depends_on=["t2"]
            ),
        ],
    )
    await store.save_plan(task.id, plan.to_context())

    loaded = TaskContext.plan_from_record((await store.get(task.id)).plan)
    assert loaded.assignments[1].status == AssignmentStatus.RUNNING

    loaded.mark_done(assignment_id="t2")
    await store.save_plan(task.id, loaded.to_context())

    reloaded = TaskContext.plan_from_record((await store.get(task.id)).plan)
    assert reloaded.assignments[1].status == AssignmentStatus.DONE
    assert reloaded.pending_ready()[0].id == "t3"

    await store.disconnect()


@pytest.mark.asyncio
async def test_mark_done_works_after_reload_from_db(db_path):
    """Simulates Coder finishing while DB still had t2 pending (pre-fix scenario)."""
    store = TaskStore(db_path)
    await store.connect()

    task = await store.create("demo", status=TaskStatus.RUNNING)
    plan = TaskPlan(
        assignments=[
            TaskAssignment(id="t1", agent="Research", task="a", status=AssignmentStatus.DONE),
            TaskAssignment(
                id="t2", agent="Coder", task="b", status=AssignmentStatus.PENDING, depends_on=["t1"]
            ),
        ],
    )
    await store.save_plan(task.id, plan.to_context())

    loaded = TaskContext.plan_from_record((await store.get(task.id)).plan)
    done = loaded.mark_done(assignment_id="t2")
    assert done is not None
    assert done.status == AssignmentStatus.DONE

    await store.disconnect()
