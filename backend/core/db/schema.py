"""Shared schema DDL for tasks, messages, artifacts, and outbox."""

from __future__ import annotations

from backend.core.db.base import Database

TASKS_DDL_SQLITE = """
CREATE TABLE IF NOT EXISTS tasks (
    id TEXT PRIMARY KEY,
    input TEXT NOT NULL,
    status TEXT NOT NULL,
    plan_json TEXT,
    context_json TEXT,
    result TEXT,
    error TEXT,
    idempotency_key TEXT,
    owner_replica TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""

TASKS_DDL_POSTGRES = """
CREATE TABLE IF NOT EXISTS tasks (
    id TEXT PRIMARY KEY,
    input TEXT NOT NULL,
    status TEXT NOT NULL,
    plan_json TEXT,
    context_json TEXT,
    result TEXT,
    error TEXT,
    idempotency_key TEXT,
    owner_replica TEXT,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL
);
"""

MESSAGES_DDL_SQLITE = """
CREATE TABLE IF NOT EXISTS task_messages (
    id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL,
    message_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""

MESSAGES_DDL_POSTGRES = """
CREATE TABLE IF NOT EXISTS task_messages (
    id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL,
    message_json TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL
);
"""

ARTIFACTS_DDL_SQLITE = """
CREATE TABLE IF NOT EXISTS artifacts (
    id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL,
    assignment_id TEXT DEFAULT '',
    type TEXT NOT NULL,
    content_json TEXT NOT NULL,
    metadata_json TEXT,
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""

ARTIFACTS_DDL_POSTGRES = """
CREATE TABLE IF NOT EXISTS artifacts (
    id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL,
    assignment_id TEXT DEFAULT '',
    type TEXT NOT NULL,
    content_json TEXT NOT NULL,
    metadata_json TEXT,
    created_by TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL
);
"""

OUTBOX_DDL_SQLITE = """
CREATE TABLE IF NOT EXISTS message_outbox (
    message_id TEXT PRIMARY KEY,
    channel TEXT NOT NULL,
    message_json TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    retries INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
"""

OUTBOX_DDL_POSTGRES = """
CREATE TABLE IF NOT EXISTS message_outbox (
    message_id TEXT PRIMARY KEY,
    channel TEXT NOT NULL,
    message_json TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    retries INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL
);
"""


async def init_schema(db: Database) -> None:
    if db.is_postgres:
        await db.execute(TASKS_DDL_POSTGRES)
        await db.execute(MESSAGES_DDL_POSTGRES)
        await db.execute(ARTIFACTS_DDL_POSTGRES)
        await db.execute(OUTBOX_DDL_POSTGRES)
        await db.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_tasks_idempotency "
            "ON tasks(idempotency_key) WHERE idempotency_key IS NOT NULL"
        )
        await db.execute("ALTER TABLE tasks ADD COLUMN IF NOT EXISTS owner_replica TEXT")
    else:
        await db.execute(TASKS_DDL_SQLITE)
        await db.execute(MESSAGES_DDL_SQLITE)
        await db.execute(ARTIFACTS_DDL_SQLITE)
        await db.execute(OUTBOX_DDL_SQLITE)
        rows = await db.fetchall("PRAGMA table_info(tasks)")
        columns = {row[1] for row in rows}
        if "owner_replica" not in columns:
            await db.execute("ALTER TABLE tasks ADD COLUMN owner_replica TEXT")
        if "context_json" not in columns:
            await db.execute("ALTER TABLE tasks ADD COLUMN context_json TEXT")
        if "error" not in columns:
            await db.execute("ALTER TABLE tasks ADD COLUMN error TEXT")
        if "idempotency_key" not in columns:
            await db.execute("ALTER TABLE tasks ADD COLUMN idempotency_key TEXT")
            await db.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_tasks_idempotency "
                "ON tasks(idempotency_key) WHERE idempotency_key IS NOT NULL"
            )

    await db.execute(
        "CREATE INDEX IF NOT EXISTS idx_tasks_status_created ON tasks(status, created_at)"
    )
    await db.execute(
        "CREATE INDEX IF NOT EXISTS idx_task_messages_task_created "
        "ON task_messages(task_id, created_at)"
    )
    await db.execute(
        "CREATE INDEX IF NOT EXISTS idx_artifacts_task_created ON artifacts(task_id, created_at)"
    )
    await db.commit()
