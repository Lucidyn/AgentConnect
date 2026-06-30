"""Tests for task store and queue."""

import pytest

from backend.core.task_queue import TaskQueue
from backend.core.task_store import TaskStore
from backend.models.task import TaskStatus


@pytest.mark.asyncio
async def test_task_queue_respects_concurrency_limit(db_path, monkeypatch):
    monkeypatch.setattr("backend.core.task_queue.settings.max_concurrent_tasks", 1)

    store = TaskStore(db_path)
    await store.connect()
    queue = TaskQueue(store)

    t1, start1 = await queue.enqueue("task one")
    t2, start2 = await queue.enqueue("task two")

    assert start1 is True
    assert start2 is False
    assert t1.status == TaskStatus.SUBMITTED
    assert t2.status == TaskStatus.QUEUED

    await store.save_result(t1.id, "done")
    next_task = await queue.on_task_finished(t1.id)
    assert next_task is not None
    assert next_task.id == t2.id

    await store.disconnect()


@pytest.mark.asyncio
async def test_task_context_persistence(db_path):
    store = TaskStore(db_path)
    await store.connect()

    task = await store.create("hello")
    await store.save_context(task.id, {"research_result": "found docs"})
    await store.save_plan(task.id, {"summary": "test", "steps": [], "assignments": []})

    loaded = await store.get(task.id)
    assert loaded is not None
    assert loaded.context["research_result"] == "found docs"
    assert loaded.plan["summary"] == "test"

    await store.disconnect()


@pytest.mark.asyncio
async def test_message_outbox_ack(db_path):
    from backend.core.message_outbox import MessageOutbox
    from backend.models.message import Message, MessageType

    outbox = MessageOutbox(db_path)
    await outbox.connect()

    msg = Message(
        from_agent="Planner",
        to_agent="Research",
        content="test",
        message_type=MessageType.TASK,
        task_id="task-1",
    ).with_trace()
    await outbox.enqueue(msg, "agent/Research")

    pending = await outbox.pending_for_channel("agent/Research")
    assert len(pending) == 1

    await outbox.ack(msg.id)
    pending = await outbox.pending_for_channel("agent/Research")
    assert len(pending) == 0

    stats = await outbox.stats()
    assert stats.get("acked", 0) == 1

    await outbox.disconnect()
