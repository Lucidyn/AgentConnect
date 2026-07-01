"""Replica claim and shared-database queue tests."""

from __future__ import annotations

import pytest

from backend.core.db.base import SQLiteDatabase
from backend.core.replica import get_replica_id, reset_replica_id_for_tests
from backend.core.task_store import TaskStore
from backend.models.task import TaskStatus


@pytest.mark.asyncio
async def test_claim_for_planning_exclusive(db_path):
    reset_replica_id_for_tests()
    store_a = TaskStore(db_path)
    store_b = TaskStore(db_path)
    await store_a.connect()
    await store_b.connect()
    try:
        task = await store_a.create("hello", status=TaskStatus.SUBMITTED)
        assert await store_a.claim_for_planning(task.id, "replica-a")
        assert not await store_b.claim_for_planning(task.id, "replica-b")

        updated = await store_a.get(task.id)
        assert updated is not None
        assert updated.status == TaskStatus.PLANNING
        assert updated.owner_replica == "replica-a"
    finally:
        await store_a.disconnect()


@pytest.mark.asyncio
async def test_dequeue_sets_owner_replica(db_path):
    reset_replica_id_for_tests()
    store = TaskStore(db_path)
    await store.connect()
    try:
        task = await store.create("queued", status=TaskStatus.QUEUED)
        claimed = await store.dequeue()
        assert claimed is not None
        assert claimed.id == task.id
        assert claimed.owner_replica == get_replica_id()
        assert claimed.status == TaskStatus.SUBMITTED
    finally:
        await store.disconnect()


@pytest.mark.asyncio
async def test_shared_sqlite_two_stores(db_path):
    """Two TaskStore handles on one file emulate multi-replica shared DB."""
    reset_replica_id_for_tests()
    store_a = TaskStore(db_path)
    store_b = TaskStore(db_path)
    await store_a.connect()
    await store_b.connect()
    try:
        await store_a.create("t1", status=TaskStatus.QUEUED)
        await store_b.create("t2", status=TaskStatus.QUEUED)

        first = await store_a.dequeue()
        second = await store_b.dequeue()
        assert first is not None
        assert second is not None
        assert first.id != second.id
        assert await store_a.dequeue() is None
    finally:
        await store_a.disconnect()
        await store_b.disconnect()
