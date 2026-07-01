"""SQLite WAL configuration tests."""

from __future__ import annotations

import pytest

from backend.core.sqlite_utils import configure_sqlite
from backend.core.task_store import TaskStore


@pytest.mark.asyncio
async def test_task_store_uses_wal_mode(isolated_paths):
    store = TaskStore(isolated_paths["tasks"])
    await store.connect()
    try:
        assert store._db is not None
        async with store._db.execute("PRAGMA journal_mode") as cursor:
            row = await cursor.fetchone()
        assert row is not None
        assert row[0].lower() == "wal"
    finally:
        await store.disconnect()


@pytest.mark.asyncio
async def test_configure_sqlite_idempotent(isolated_paths):
    import aiosqlite

    db = await aiosqlite.connect(isolated_paths["tasks"])
    await configure_sqlite(db)
    await configure_sqlite(db)
    async with db.execute("PRAGMA journal_mode") as cursor:
        mode = (await cursor.fetchone())[0]
    assert mode.lower() == "wal"
    await db.close()
