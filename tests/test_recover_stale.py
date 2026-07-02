"""Stale task recovery tests."""

import pytest

from backend.core.task_store import TaskStore
from backend.models.task import TaskStatus


@pytest.mark.asyncio
async def test_recover_stale_running_and_waiting_approval(db_path):
    store = TaskStore(db_path)
    await store.connect()

    running = await store.create("run", status=TaskStatus.RUNNING)
    waiting = await store.create("wait", status=TaskStatus.WAITING_APPROVAL)
    queued = await store.create("q", status=TaskStatus.QUEUED)

    await store.recover_stale_tasks()

    assert (await store.get(running.id)).status == TaskStatus.QUEUED
    assert (await store.get(waiting.id)).status == TaskStatus.QUEUED
    assert (await store.get(queued.id)).status == TaskStatus.QUEUED

    await store.disconnect()
