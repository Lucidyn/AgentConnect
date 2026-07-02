"""PostgreSQL-backed task store (requires DATABASE_URL or local postgres)."""

from __future__ import annotations

import os

import pytest

from backend.config import settings
from backend.core.db import create_database
from backend.core.db.schema import init_schema
from backend.core.task_store import TaskStore
from backend.models.task import TaskStatus


def _postgres_url() -> str | None:
    return (os.environ.get("DATABASE_URL") or settings.database_url or "").strip() or None


@pytest.fixture
async def postgres_db():
    url = _postgres_url()
    if not url:
        pytest.skip("DATABASE_URL not set")
    db = await create_database(database_url=url)
    await init_schema(db)
    yield db
    await db.disconnect()


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_postgres_dequeue_skip_locked(postgres_db):
    store_a = TaskStore(postgres_db)
    store_b = TaskStore(postgres_db)
    await store_a.create("job-a", status=TaskStatus.QUEUED)
    await store_b.create("job-b", status=TaskStatus.QUEUED)

    claimed_a = await store_a.dequeue()
    claimed_b = await store_b.dequeue()
    assert claimed_a is not None
    assert claimed_b is not None
    assert claimed_a.id != claimed_b.id


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_postgres_claim_for_planning(postgres_db):
    store = TaskStore(postgres_db)
    task = await store.create("plan-me", status=TaskStatus.SUBMITTED)
    assert await store.claim_for_planning(task.id, "pg-replica-1")
    assert not await store.claim_for_planning(task.id, "pg-replica-2")
    row = await store.get(task.id)
    assert row is not None
    assert row.status == TaskStatus.PLANNING
    assert row.owner_replica == "pg-replica-1"
