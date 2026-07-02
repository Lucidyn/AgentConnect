"""Task queue — limits concurrent runs and dispatches queued work."""

from __future__ import annotations

import logging

from backend.config import settings
from backend.core.task_store import TaskStore
from backend.models.message import Message, MessageType
from backend.models.task import TaskRecord, TaskStatus

logger = logging.getLogger(__name__)

_TERMINAL_STATUSES = frozenset(
    {TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED}
)


class TaskQueue:
    def __init__(self, store: TaskStore) -> None:
        self._store = store
        self._max = settings.max_concurrent_tasks

    async def enqueue(
        self, user_input: str, idempotency_key: str | None = None
    ) -> tuple[TaskRecord, bool]:
        if idempotency_key:
            existing = await self._store.get_by_idempotency_key(idempotency_key)
            if existing:
                return existing, False

        active = await self._store.count_active()
        if active >= self._max:
            task = await self._store.create(
                user_input, status=TaskStatus.QUEUED, idempotency_key=idempotency_key
            )
            logger.info("Task %s queued (%d/%d active)", task.id, active, self._max)
            return task, False
        task = await self._store.create(
            user_input, status=TaskStatus.SUBMITTED, idempotency_key=idempotency_key
        )
        return task, True

    async def build_start_message(self, task: TaskRecord) -> Message:
        return Message(
            from_agent="User",
            to_agent="Planner",
            content=task.input,
            message_type=MessageType.TASK,
            task_id=task.id,
            metadata={"task_id": task.id},
        )

    async def on_task_finished(self, task_id: str) -> TaskRecord | None:
        """Start next queued task after one completes. Returns started task if any."""
        finished = await self._store.get(task_id)
        if not finished or finished.status not in _TERMINAL_STATUSES:
            logger.debug(
                "Skip queue dequeue for task %s (status=%s)",
                task_id,
                finished.status if finished else None,
            )
            return None
        if await self._store.count_queued() == 0:
            return None
        if await self._store.count_active() >= self._max:
            return None
        next_task = await self._store.dequeue()
        if not next_task:
            return None
        await self._store.update_status(next_task.id, TaskStatus.SUBMITTED)
        logger.info("Dequeuing task %s", next_task.id)
        return next_task

    @property
    def max_concurrent(self) -> int:
        return self._max
