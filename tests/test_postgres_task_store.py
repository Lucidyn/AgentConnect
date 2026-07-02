"""Postgres-backed task store integration tests."""

from __future__ import annotations

import os

import pytest

from backend.core.task_store import TaskStore
from backend.models.task import TaskStatus


pytestmark = pytest.mark.postgres


@pytest.fixture
async def postgres_store(monkeypatch):
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        pytest.skip("DATABASE_URL not set")
    monkeypatch.setattr("backend.config.settings.database_url", url)
    store = TaskStore()
    await store.connect()
    yield store
    await store.disconnect()


@pytest.mark.asyncio
async def test_postgres_tenant_isolation(postgres_store):
    task_a = await postgres_store.create("tenant-a task", tenant_id="alpha")
    task_b = await postgres_store.create("tenant-b task", tenant_id="beta")

    assert await postgres_store.get(task_a.id, tenant_id="alpha")
    assert await postgres_store.get(task_a.id, tenant_id="beta") is None
    assert await postgres_store.get(task_b.id, tenant_id="beta")
    assert await postgres_store.get(task_b.id, tenant_id="alpha") is None

    alpha_tasks = await postgres_store.list_tasks(limit=10, tenant_id="alpha")
    assert all(t.tenant_id == "alpha" for t in alpha_tasks)
    assert task_a.id in {t.id for t in alpha_tasks}
    assert task_b.id not in {t.id for t in alpha_tasks}


@pytest.mark.asyncio
async def test_postgres_idempotency_scoped_by_tenant(postgres_store):
    first = await postgres_store.create(
        "once",
        idempotency_key="idem-1",
        tenant_id="alpha",
    )
    dup = await postgres_store.get_by_idempotency_key("idem-1", tenant_id="alpha")
    assert dup and dup.id == first.id

    other = await postgres_store.get_by_idempotency_key("idem-1", tenant_id="beta")
    assert other is None

    second = await postgres_store.create(
        "once-beta",
        idempotency_key="idem-1",
        tenant_id="beta",
        status=TaskStatus.QUEUED,
    )
    assert second.id != first.id
