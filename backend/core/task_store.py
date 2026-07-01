"""Task persistence — SQLite store for task lifecycle, context, and queue."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

import aiosqlite

from backend.config import settings
from backend.constants import MAX_PROCESSED_MESSAGE_IDS
from backend.core.metrics import TASKS_FINISHED
from backend.models.artifact import Artifact
from backend.models.message import Message
from backend.models.task import TaskRecord, TaskStatus

logger = logging.getLogger(__name__)

_ACTIVE_STATUSES = (
    TaskStatus.SUBMITTED,
    TaskStatus.PLANNING,
    TaskStatus.RUNNING,
    TaskStatus.WAITING_APPROVAL,
)

_RECOVER_STATUSES = _ACTIVE_STATUSES

_TASK_SELECT = """
    SELECT id, input, status, plan_json, result, created_at, updated_at, context_json, error, idempotency_key
    FROM tasks
"""


class TaskStore:
    def __init__(self, db_path: str | None = None) -> None:
        self._db_path = db_path or settings.tasks_db_path
        self._db: aiosqlite.Connection | None = None

    async def connect(self) -> None:
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        self._db = await aiosqlite.connect(self._db_path)
        await self._db.execute(
            """
            CREATE TABLE IF NOT EXISTS tasks (
                id TEXT PRIMARY KEY,
                input TEXT NOT NULL,
                status TEXT NOT NULL,
                plan_json TEXT,
                context_json TEXT,
                result TEXT,
                error TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        await self._db.execute(
            """
            CREATE TABLE IF NOT EXISTS task_messages (
                id TEXT PRIMARY KEY,
                task_id TEXT NOT NULL,
                message_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        await self._db.execute(
            """
            CREATE TABLE IF NOT EXISTS artifacts (
                id TEXT PRIMARY KEY,
                task_id TEXT NOT NULL,
                assignment_id TEXT DEFAULT '',
                type TEXT NOT NULL,
                content_json TEXT NOT NULL,
                metadata_json TEXT,
                created_by TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        await self._migrate_columns()
        await self._create_indexes()
        await self._db.commit()

    async def _migrate_columns(self) -> None:
        assert self._db is not None
        async with self._db.execute("PRAGMA table_info(tasks)") as cursor:
            columns = {row[1] for row in await cursor.fetchall()}
        if "context_json" not in columns:
            await self._db.execute("ALTER TABLE tasks ADD COLUMN context_json TEXT")
        if "error" not in columns:
            await self._db.execute("ALTER TABLE tasks ADD COLUMN error TEXT")
        if "idempotency_key" not in columns:
            await self._db.execute("ALTER TABLE tasks ADD COLUMN idempotency_key TEXT")
            await self._db.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_tasks_idempotency ON tasks(idempotency_key) "
                "WHERE idempotency_key IS NOT NULL"
            )

    async def _create_indexes(self) -> None:
        assert self._db is not None
        await self._db.execute(
            "CREATE INDEX IF NOT EXISTS idx_tasks_status_created ON tasks(status, created_at)"
        )
        await self._db.execute(
            "CREATE INDEX IF NOT EXISTS idx_task_messages_task_created "
            "ON task_messages(task_id, created_at)"
        )
        await self._db.execute(
            "CREATE INDEX IF NOT EXISTS idx_artifacts_task_created "
            "ON artifacts(task_id, created_at)"
        )

    async def disconnect(self) -> None:
        if self._db:
            await self._db.close()

    async def create(
        self,
        user_input: str,
        status: TaskStatus = TaskStatus.SUBMITTED,
        idempotency_key: str | None = None,
    ) -> TaskRecord:
        task = TaskRecord(input=user_input, status=status, idempotency_key=idempotency_key)
        await self._save(task)
        return task

    async def get_by_idempotency_key(self, key: str) -> TaskRecord | None:
        if not key:
            return None
        assert self._db is not None
        async with self._db.execute(
            f"""
            {_TASK_SELECT.strip()}
            WHERE idempotency_key = ?
            """,
            (key,),
        ) as cursor:
            row = await cursor.fetchone()
        return self._row_to_task(row) if row else None

    async def get(self, task_id: str) -> TaskRecord | None:
        assert self._db is not None
        async with self._db.execute(
            f"""
            {_TASK_SELECT.strip()}
            WHERE id = ?
            """,
            (task_id,),
        ) as cursor:
            row = await cursor.fetchone()
        return self._row_to_task(row) if row else None

    async def list_tasks(self, limit: int = 20) -> list[TaskRecord]:
        assert self._db is not None
        async with self._db.execute(
            f"""
            {_TASK_SELECT.strip()}
            ORDER BY created_at DESC LIMIT ?
            """,
            (limit,),
        ) as cursor:
            rows = await cursor.fetchall()
        return [self._row_to_task(row) for row in rows]

    async def recover_stale_tasks(self) -> None:
        """Re-queue tasks that were active when the server last stopped."""
        assert self._db is not None
        for status in _RECOVER_STATUSES:
            async with self._db.execute(
                "SELECT id FROM tasks WHERE status = ?", (status.value,)
            ) as cursor:
                rows = await cursor.fetchall()
            for (task_id,) in rows:
                await self._recover_plan_assignments(task_id)
                await self.update_status(task_id, TaskStatus.QUEUED)
                logger.info("Recovered stale task %s → queued", task_id)

    async def _recover_plan_assignments(self, task_id: str) -> None:
        """Reset RUNNING sub-assignments so dispatch can resume after restart."""
        from backend.models.task_context import TaskContext

        task = await self.get(task_id)
        if not task or not task.plan:
            return
        plan = TaskContext.plan_from_record(task.plan)
        if not plan:
            return
        reset = plan.reset_running_to_pending()
        if reset:
            await self.save_plan(task_id, plan.to_context())
            logger.info("Reset %d RUNNING assignment(s) for task %s", reset, task_id)

    async def count_active(self) -> int:
        assert self._db is not None
        placeholders = ",".join("?" for _ in _ACTIVE_STATUSES)
        async with self._db.execute(
            f"SELECT COUNT(*) FROM tasks WHERE status IN ({placeholders})",
            [s.value for s in _ACTIVE_STATUSES],
        ) as cursor:
            row = await cursor.fetchone()
        return row[0] if row else 0

    async def count_queued(self) -> int:
        assert self._db is not None
        async with self._db.execute(
            "SELECT COUNT(*) FROM tasks WHERE status = ?", (TaskStatus.QUEUED.value,)
        ) as cursor:
            row = await cursor.fetchone()
        return row[0] if row else 0

    async def dequeue(self) -> TaskRecord | None:
        assert self._db is not None
        async with self._db.execute(
            f"""
            UPDATE tasks
            SET status = ?, updated_at = ?
            WHERE id = (
                SELECT id FROM tasks WHERE status = ? ORDER BY created_at LIMIT 1
            )
            RETURNING id, input, status, plan_json, result, created_at, updated_at,
                      context_json, error, idempotency_key
            """,
            (
                TaskStatus.SUBMITTED.value,
                datetime.now(timezone.utc).isoformat(),
                TaskStatus.QUEUED.value,
            ),
        ) as cursor:
            row = await cursor.fetchone()
        await self._db.commit()
        return self._row_to_task(row) if row else None

    async def update_status(self, task_id: str, status: TaskStatus) -> None:
        assert self._db is not None
        await self._db.execute(
            "UPDATE tasks SET status = ?, updated_at = ? WHERE id = ?",
            (status.value, datetime.now(timezone.utc).isoformat(), task_id),
        )
        await self._db.commit()

    async def save_plan(self, task_id: str, plan: dict) -> None:
        task = await self.get(task_id)
        if not task:
            return
        status = task.status
        if status not in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.QUEUED):
            status = TaskStatus.RUNNING
        assert self._db is not None
        await self._db.execute(
            """
            UPDATE tasks SET plan_json = ?, status = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                json.dumps(plan, ensure_ascii=False) if plan else None,
                status.value,
                datetime.now(timezone.utc).isoformat(),
                task_id,
            ),
        )
        await self._db.commit()

    async def save_context(self, task_id: str, context: dict) -> None:
        assert self._db is not None
        await self._db.execute(
            "UPDATE tasks SET context_json = ?, updated_at = ? WHERE id = ?",
            (
                json.dumps(context, ensure_ascii=False) if context else None,
                datetime.now(timezone.utc).isoformat(),
                task_id,
            ),
        )
        await self._db.commit()

    async def is_message_processed(self, task_id: str, message_id: str) -> bool:
        task = await self.get(task_id)
        if not task:
            return False
        ids = (task.context or {}).get("processed_message_ids", [])
        return message_id in ids

    async def mark_message_processed(self, task_id: str, message_id: str) -> None:
        task = await self.get(task_id)
        if not task:
            return
        ctx = dict(task.context or {})
        ids: list[str] = list(ctx.get("processed_message_ids", []))
        if message_id in ids:
            return
        ids.append(message_id)
        if len(ids) > MAX_PROCESSED_MESSAGE_IDS:
            ids = ids[-MAX_PROCESSED_MESSAGE_IDS:]
        ctx["processed_message_ids"] = ids
        await self.save_context(task_id, ctx)

    async def save_result(self, task_id: str, result: str) -> None:
        assert self._db is not None
        await self._db.execute(
            "UPDATE tasks SET result = ?, status = ?, updated_at = ? WHERE id = ?",
            (
                result,
                TaskStatus.COMPLETED.value,
                datetime.now(timezone.utc).isoformat(),
                task_id,
            ),
        )
        await self._db.commit()
        if TASKS_FINISHED:
            TASKS_FINISHED.labels(status="completed").inc()

    async def mark_failed(self, task_id: str, error: str) -> None:
        assert self._db is not None
        await self._db.execute(
            "UPDATE tasks SET error = ?, status = ?, updated_at = ? WHERE id = ?",
            (
                error,
                TaskStatus.FAILED.value,
                datetime.now(timezone.utc).isoformat(),
                task_id,
            ),
        )
        await self._db.commit()
        if TASKS_FINISHED:
            TASKS_FINISHED.labels(status="failed").inc()

    async def log_message(self, message: Message) -> None:
        if not message.task_id:
            return
        assert self._db is not None
        await self._db.execute(
            "INSERT OR REPLACE INTO task_messages (id, task_id, message_json, created_at) VALUES (?, ?, ?, ?)",
            (message.id, message.task_id, message.model_dump_json(), message.timestamp.isoformat()),
        )
        await self._db.commit()

    async def get_messages(self, task_id: str) -> list[Message]:
        assert self._db is not None
        async with self._db.execute(
            "SELECT message_json FROM task_messages WHERE task_id = ? ORDER BY created_at",
            (task_id,),
        ) as cursor:
            rows = await cursor.fetchall()
        return [Message.model_validate_json(row[0]) for row in rows]

    async def find_by_trace(self, trace_id: str, limit: int = 100) -> list[Message]:
        assert self._db is not None
        async with self._db.execute(
            """
            SELECT message_json FROM task_messages
            WHERE json_extract(message_json, '$.trace_id') = ?
            ORDER BY created_at LIMIT ?
            """,
            (trace_id, limit),
        ) as cursor:
            rows = await cursor.fetchall()
        return [Message.model_validate_json(row[0]) for row in rows]

    async def save_artifact(self, artifact: Artifact) -> Artifact:
        assert self._db is not None
        await self._db.execute(
            """
            INSERT OR REPLACE INTO artifacts
            (id, task_id, assignment_id, type, content_json, metadata_json, created_by, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                artifact.id,
                artifact.task_id,
                artifact.assignment_id,
                artifact.type,
                json.dumps(artifact.content, ensure_ascii=False),
                json.dumps(artifact.metadata, ensure_ascii=False),
                artifact.created_by,
                artifact.created_at.isoformat(),
            ),
        )
        await self._db.commit()
        return artifact

    async def list_artifacts(self, task_id: str) -> list[Artifact]:
        assert self._db is not None
        async with self._db.execute(
            """
            SELECT id, task_id, assignment_id, type, content_json, metadata_json, created_by, created_at
            FROM artifacts WHERE task_id = ? ORDER BY created_at
            """,
            (task_id,),
        ) as cursor:
            rows = await cursor.fetchall()
        return [self._row_to_artifact(row) for row in rows]

    async def get_artifact(self, artifact_id: str) -> Artifact | None:
        assert self._db is not None
        async with self._db.execute(
            """
            SELECT id, task_id, assignment_id, type, content_json, metadata_json, created_by, created_at
            FROM artifacts WHERE id = ?
            """,
            (artifact_id,),
        ) as cursor:
            row = await cursor.fetchone()
        return self._row_to_artifact(row) if row else None

    async def _save(self, task: TaskRecord) -> None:
        assert self._db is not None
        await self._db.execute(
            """
            INSERT OR REPLACE INTO tasks
            (id, input, status, plan_json, context_json, result, error, idempotency_key, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                task.id,
                task.input,
                task.status.value,
                json.dumps(task.plan, ensure_ascii=False) if task.plan else None,
                json.dumps(task.context, ensure_ascii=False) if task.context else None,
                task.result,
                task.error,
                task.idempotency_key,
                task.created_at.isoformat(),
                task.updated_at.isoformat(),
            ),
        )
        await self._db.commit()

    @staticmethod
    def _row_to_task(row: tuple) -> TaskRecord:
        return TaskRecord(
            id=row[0],
            input=row[1],
            status=TaskStatus(row[2]),
            plan=json.loads(row[3]) if row[3] else None,
            result=row[4],
            created_at=datetime.fromisoformat(row[5]),
            updated_at=datetime.fromisoformat(row[6]),
            context=json.loads(row[7]) if row[7] else {},
            error=row[8],
            idempotency_key=row[9] if len(row) > 9 else None,
        )

    @staticmethod
    def _row_to_artifact(row: tuple) -> Artifact:
        return Artifact(
            id=row[0],
            task_id=row[1],
            assignment_id=row[2] or "",
            type=row[3],
            content=json.loads(row[4]),
            metadata=json.loads(row[5]) if row[5] else {},
            created_by=row[6],
            created_at=datetime.fromisoformat(row[7]),
        )
