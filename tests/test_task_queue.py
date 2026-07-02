"""Task queue dequeue guard tests."""

from __future__ import annotations

import pytest

from backend.core.task_queue import TaskQueue
from backend.core.task_store import TaskStore
from backend.models.task import TaskStatus


@pytest.mark.asyncio
async def test_on_task_finished_skips_non_terminal(db_path, patch_settings):
    patch_settings(max_concurrent_tasks=1)

    store = TaskStore(db_path)
    await store.connect()
    queue = TaskQueue(store)

    running = await store.create("running task", status=TaskStatus.RUNNING)
    queued = await store.create("queued task", status=TaskStatus.QUEUED)

    started = await queue.on_task_finished(running.id)
    assert started is None
    assert (await store.get(queued.id)).status == TaskStatus.QUEUED

    await store.disconnect()


@pytest.mark.asyncio
async def test_on_task_finished_starts_next_when_slot_free(db_path, patch_settings):
    patch_settings(max_concurrent_tasks=1)

    store = TaskStore(db_path)
    await store.connect()
    queue = TaskQueue(store)

    first, _ = await queue.enqueue("first")
    await store.update_status(first.id, TaskStatus.RUNNING)
    second = await store.create("second", status=TaskStatus.QUEUED)

    await store.update_status(first.id, TaskStatus.COMPLETED)
    started = await queue.on_task_finished(first.id)

    assert started is not None
    assert started.id == second.id
    assert (await store.get(second.id)).status == TaskStatus.SUBMITTED

    await store.disconnect()
