"""Task persistence — SQLite or PostgreSQL store for task lifecycle and queue."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from backend.config import settings
from backend.constants import MAX_PROCESSED_MESSAGE_IDS
from backend.core.db.base import Database, create_database
from backend.core.db.schema import init_schema
from backend.core.metrics import TASKS_FINISHED
from backend.core.replica import get_replica_id
from backend.models.artifact import Artifact
from backend.models.message import Message
from backend.models.task import TaskRecord, TaskStatus

logger = logging.getLogger(__name__)

# Occupies a concurrent execution slot (waiting_approval does not).
_RUNNING_STATUSES = (
    TaskStatus.SUBMITTED,
    TaskStatus.PLANNING,
    TaskStatus.RUNNING,
)

_RECOVER_STATUSES = _RUNNING_STATUSES + (TaskStatus.WAITING_APPROVAL,)

_TASK_SELECT = """
    SELECT id, input, status, plan_json, result, created_at, updated_at,
           context_json, error, idempotency_key, owner_replica, tenant_id
    FROM tasks
"""


class TaskStore:
    def __init__(self, db_or_path: Database | str | None = None) -> None:
        if isinstance(db_or_path, Database):
            self._db = db_or_path
            self._db_path: str | None = None
            self._owns_db = False
        else:
            self._db = None
            self._db_path = db_or_path or settings.tasks_db_path
            self._owns_db = False

    @property
    def database(self) -> Database | None:
        return self._db

    async def connect(self) -> None:
        if self._db is None:
            self._db = await create_database(sqlite_path=self._db_path)
            self._owns_db = True
        await init_schema(self._db)

    async def disconnect(self) -> None:
        if self._owns_db and self._db:
            await self._db.disconnect()
        self._db = None
        self._owns_db = False

    def _ts(self) -> Any:
        now = datetime.now(timezone.utc)
        if self._db and self._db.is_postgres:
            return now
        return now.isoformat()

    def _upsert_task_sql(self) -> str:
        if self._db and self._db.is_postgres:
            return """
            INSERT INTO tasks
            (id, tenant_id, input, status, plan_json, context_json, result, error,
             idempotency_key, owner_replica, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (id) DO UPDATE SET
                tenant_id = EXCLUDED.tenant_id,
                input = EXCLUDED.input,
                status = EXCLUDED.status,
                plan_json = EXCLUDED.plan_json,
                context_json = EXCLUDED.context_json,
                result = EXCLUDED.result,
                error = EXCLUDED.error,
                idempotency_key = EXCLUDED.idempotency_key,
                owner_replica = EXCLUDED.owner_replica,
                updated_at = EXCLUDED.updated_at
            """
        return """
            INSERT OR REPLACE INTO tasks
            (id, tenant_id, input, status, plan_json, context_json, result, error,
             idempotency_key, owner_replica, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """

    def _upsert_message_sql(self) -> str:
        if self._db and self._db.is_postgres:
            return """
            INSERT INTO task_messages (id, task_id, message_json, created_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT (id) DO UPDATE SET
                task_id = EXCLUDED.task_id,
                message_json = EXCLUDED.message_json,
                created_at = EXCLUDED.created_at
            """
        return """
            INSERT OR REPLACE INTO task_messages (id, task_id, message_json, created_at)
            VALUES (?, ?, ?, ?)
            """

    def _upsert_artifact_sql(self) -> str:
        if self._db and self._db.is_postgres:
            return """
            INSERT INTO artifacts
            (id, task_id, assignment_id, type, content_json, metadata_json, created_by, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (id) DO UPDATE SET
                task_id = EXCLUDED.task_id,
                assignment_id = EXCLUDED.assignment_id,
                type = EXCLUDED.type,
                content_json = EXCLUDED.content_json,
                metadata_json = EXCLUDED.metadata_json,
                created_by = EXCLUDED.created_by,
                created_at = EXCLUDED.created_at
            """
        return """
            INSERT OR REPLACE INTO artifacts
            (id, task_id, assignment_id, type, content_json, metadata_json, created_by, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """

    async def create(
        self,
        user_input: str,
        status: TaskStatus = TaskStatus.SUBMITTED,
        idempotency_key: str | None = None,
        tenant_id: str = "default",
    ) -> TaskRecord:
        task = TaskRecord(
            input=user_input,
            status=status,
            idempotency_key=idempotency_key,
            tenant_id=tenant_id,
        )
        await self._save(task)
        return task

    async def get_by_idempotency_key(
        self, key: str, tenant_id: str = "default"
    ) -> TaskRecord | None:
        if not key:
            return None
        assert self._db is not None
        row = await self._db.fetchone(
            f"{_TASK_SELECT.strip()} WHERE tenant_id = ? AND idempotency_key = ?",
            (tenant_id, key),
        )
        return self._row_to_task(row) if row else None

    async def get(self, task_id: str, tenant_id: str | None = None) -> TaskRecord | None:
        assert self._db is not None
        if tenant_id:
            row = await self._db.fetchone(
                f"{_TASK_SELECT.strip()} WHERE id = ? AND tenant_id = ?",
                (task_id, tenant_id),
            )
        else:
            row = await self._db.fetchone(
                f"{_TASK_SELECT.strip()} WHERE id = ?",
                (task_id,),
            )
        return self._row_to_task(row) if row else None

    async def list_tasks(self, limit: int = 20, tenant_id: str | None = None) -> list[TaskRecord]:
        assert self._db is not None
        if tenant_id:
            rows = await self._db.fetchall(
                f"{_TASK_SELECT.strip()} WHERE tenant_id = ? ORDER BY created_at DESC LIMIT ?",
                (tenant_id, limit),
            )
        else:
            rows = await self._db.fetchall(
                f"{_TASK_SELECT.strip()} ORDER BY created_at DESC LIMIT ?",
                (limit,),
            )
        return [self._row_to_task(row) for row in rows]

    async def recover_stale_tasks(self) -> None:
        """Re-queue tasks that were active when the server last stopped."""
        from backend.core.plan_recovery import recover_plan_assignments

        assert self._db is not None
        for status in _RECOVER_STATUSES:
            rows = await self._db.fetchall(
                "SELECT id FROM tasks WHERE status = ?",
                (status.value,),
            )
            for (task_id,) in rows:
                await recover_plan_assignments(self, task_id)
                await self.update_status(task_id, TaskStatus.QUEUED)
                logger.info("Recovered stale task %s → queued", task_id)

    async def count_active(self) -> int:
        """Tasks occupying a concurrent execution slot."""
        assert self._db is not None
        placeholders = ",".join("?" for _ in _RUNNING_STATUSES)
        row = await self._db.fetchone(
            f"SELECT COUNT(*) FROM tasks WHERE status IN ({placeholders})",
            tuple(s.value for s in _RUNNING_STATUSES),
        )
        return row[0] if row else 0

    async def count_waiting_approval(self) -> int:
        assert self._db is not None
        row = await self._db.fetchone(
            "SELECT COUNT(*) FROM tasks WHERE status = ?",
            (TaskStatus.WAITING_APPROVAL.value,),
        )
        return row[0] if row else 0

    async def get_queue_info(self, task_id: str) -> dict[str, int]:
        """Queue position and rough wait estimate for a queued task."""
        assert self._db is not None
        task = await self.get(task_id)
        if not task or task.status != TaskStatus.QUEUED:
            return {
                "queue_position": 0,
                "queued_ahead": 0,
                "running_count": await self.count_active(),
                "estimated_wait_seconds": 0,
            }

        rows = await self._db.fetchall(
            "SELECT id FROM tasks WHERE status = ? ORDER BY created_at ASC",
            (TaskStatus.QUEUED.value,),
        )
        ids = [row[0] for row in rows]
        try:
            position = ids.index(task_id) + 1
        except ValueError:
            position = 0

        running = await self.count_active()
        max_c = max(1, settings.max_concurrent_tasks)
        avg = max(30, settings.queue_avg_task_seconds)
        ahead = max(0, position - 1)
        slots_free = max(0, max_c - running)

        if position <= slots_free:
            estimated = 0
        else:
            need_to_wait = position - slots_free
            waves = (need_to_wait + max_c - 1) // max_c
            estimated = waves * avg

        return {
            "queue_position": position,
            "queued_ahead": ahead,
            "running_count": running,
            "estimated_wait_seconds": estimated,
        }

    async def count_queued(self) -> int:
        assert self._db is not None
        row = await self._db.fetchone(
            "SELECT COUNT(*) FROM tasks WHERE status = ?",
            (TaskStatus.QUEUED.value,),
        )
        return row[0] if row else 0

    async def dequeue(self) -> TaskRecord | None:
        assert self._db is not None
        replica_id = get_replica_id()
        now = self._ts()
        if self._db.is_postgres:
            sql = f"""
            UPDATE tasks
            SET status = ?, updated_at = ?, owner_replica = ?
            WHERE id = (
                SELECT id FROM tasks WHERE status = ?
                ORDER BY created_at
                FOR UPDATE SKIP LOCKED
                LIMIT 1
            )
            RETURNING id, input, status, plan_json, result, created_at, updated_at,
                      context_json, error, idempotency_key, owner_replica, tenant_id
            """
        else:
            sql = f"""
            UPDATE tasks
            SET status = ?, updated_at = ?, owner_replica = ?
            WHERE id = (
                SELECT id FROM tasks WHERE status = ? ORDER BY created_at LIMIT 1
            )
            RETURNING id, input, status, plan_json, result, created_at, updated_at,
                      context_json, error, idempotency_key, owner_replica, tenant_id
            """
        row = await self._db.fetchone(
            sql,
            (
                TaskStatus.SUBMITTED.value,
                now,
                replica_id,
                TaskStatus.QUEUED.value,
            ),
        )
        await self._db.commit()
        return self._row_to_task(row) if row else None

    async def claim_for_planning(self, task_id: str, replica_id: str | None = None) -> bool:
        """Atomically claim a submitted task for planning on this API replica."""
        assert self._db is not None
        replica = replica_id or get_replica_id()
        now = self._ts()
        sql = """
            UPDATE tasks SET status = ?, owner_replica = ?, updated_at = ?
            WHERE id = ? AND status = ?
            AND (owner_replica IS NULL OR owner_replica = ?)
            RETURNING id
            """
        row = await self._db.fetchone(
            sql,
            (
                TaskStatus.PLANNING.value,
                replica,
                now,
                task_id,
                TaskStatus.SUBMITTED.value,
                replica,
            ),
        )
        await self._db.commit()
        return row is not None

    async def update_status(self, task_id: str, status: TaskStatus) -> None:
        assert self._db is not None
        await self._db.execute(
            "UPDATE tasks SET status = ?, updated_at = ? WHERE id = ?",
            (status.value, self._ts(), task_id),
        )
        await self._db.commit()

    async def save_plan(self, task_id: str, plan: dict) -> None:
        assert self._db is not None
        await self._db.execute(
            "UPDATE tasks SET plan_json = ?, updated_at = ? WHERE id = ?",
            (
                json.dumps(plan, ensure_ascii=False) if plan else None,
                self._ts(),
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
                self._ts(),
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
            (result, TaskStatus.COMPLETED.value, self._ts(), task_id),
        )
        await self._db.commit()
        if TASKS_FINISHED:
            TASKS_FINISHED.labels(status="completed").inc()

    async def mark_failed(self, task_id: str, error: str) -> None:
        assert self._db is not None
        await self._db.execute(
            "UPDATE tasks SET error = ?, status = ?, updated_at = ? WHERE id = ?",
            (error, TaskStatus.FAILED.value, self._ts(), task_id),
        )
        await self._db.commit()
        if TASKS_FINISHED:
            TASKS_FINISHED.labels(status="failed").inc()

    async def log_message(self, message: Message) -> None:
        if not message.task_id:
            return
        assert self._db is not None
        ts = message.timestamp
        if self._db.is_postgres:
            ts_val = ts
        else:
            ts_val = ts.isoformat()
        await self._db.execute(
            self._upsert_message_sql(),
            (message.id, message.task_id, message.model_dump_json(), ts_val),
        )
        await self._db.commit()

    async def get_messages(self, task_id: str) -> list[Message]:
        assert self._db is not None
        rows = await self._db.fetchall(
            "SELECT message_json FROM task_messages WHERE task_id = ? ORDER BY created_at",
            (task_id,),
        )
        return [Message.model_validate_json(row[0]) for row in rows]

    async def find_by_trace(self, trace_id: str, limit: int = 100) -> list[Message]:
        assert self._db is not None
        if self._db.is_postgres:
            sql = """
            SELECT message_json FROM task_messages
            WHERE message_json::jsonb->>'trace_id' = ?
            ORDER BY created_at LIMIT ?
            """
        else:
            sql = """
            SELECT message_json FROM task_messages
            WHERE json_extract(message_json, '$.trace_id') = ?
            ORDER BY created_at LIMIT ?
            """
        rows = await self._db.fetchall(sql, (trace_id, limit))
        return [Message.model_validate_json(row[0]) for row in rows]

    async def save_artifact(self, artifact: Artifact) -> Artifact:
        assert self._db is not None
        created = artifact.created_at
        created_val = created if self._db.is_postgres else created.isoformat()
        await self._db.execute(
            self._upsert_artifact_sql(),
            (
                artifact.id,
                artifact.task_id,
                artifact.assignment_id,
                artifact.type,
                json.dumps(artifact.content, ensure_ascii=False),
                json.dumps(artifact.metadata, ensure_ascii=False),
                artifact.created_by,
                created_val,
            ),
        )
        await self._db.commit()
        return artifact

    async def list_artifacts(self, task_id: str) -> list[Artifact]:
        assert self._db is not None
        rows = await self._db.fetchall(
            """
            SELECT id, task_id, assignment_id, type, content_json, metadata_json, created_by, created_at
            FROM artifacts WHERE task_id = ? ORDER BY created_at
            """,
            (task_id,),
        )
        return [self._row_to_artifact(row) for row in rows]

    async def get_artifact(self, artifact_id: str) -> Artifact | None:
        assert self._db is not None
        row = await self._db.fetchone(
            """
            SELECT id, task_id, assignment_id, type, content_json, metadata_json, created_by, created_at
            FROM artifacts WHERE id = ?
            """,
            (artifact_id,),
        )
        return self._row_to_artifact(row) if row else None

    async def _save(self, task: TaskRecord) -> None:
        assert self._db is not None
        created = task.created_at
        updated = task.updated_at
        if self._db.is_postgres:
            created_val, updated_val = created, updated
        else:
            created_val, updated_val = created.isoformat(), updated.isoformat()
        await self._db.execute(
            self._upsert_task_sql(),
            (
                task.id,
                task.tenant_id,
                task.input,
                task.status.value,
                json.dumps(task.plan, ensure_ascii=False) if task.plan else None,
                json.dumps(task.context, ensure_ascii=False) if task.context else None,
                task.result,
                task.error,
                task.idempotency_key,
                task.owner_replica,
                created_val,
                updated_val,
            ),
        )
        await self._db.commit()

    @staticmethod
    def _parse_dt(value: Any) -> datetime:
        if isinstance(value, datetime):
            return value
        return datetime.fromisoformat(str(value))

    @staticmethod
    def _row_to_task(row: tuple) -> TaskRecord:
        return TaskRecord(
            id=row[0],
            input=row[1],
            status=TaskStatus(row[2]),
            plan=json.loads(row[3]) if row[3] else None,
            result=row[4],
            created_at=TaskStore._parse_dt(row[5]),
            updated_at=TaskStore._parse_dt(row[6]),
            context=json.loads(row[7]) if row[7] else {},
            error=row[8],
            idempotency_key=row[9] if len(row) > 9 else None,
            owner_replica=row[10] if len(row) > 10 else None,
            tenant_id=row[11] if len(row) > 11 else "default",
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
            created_at=TaskStore._parse_dt(row[7]),
        )
