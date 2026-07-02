"""Task idempotency, cancel, trace, and dead-letter tests."""

import pytest

from backend.core.message_outbox import MessageOutbox
from backend.core.task_queue import TaskQueue
from backend.core.task_store import TaskStore
from backend.models.message import Message, MessageType
from backend.models.task import TaskStatus


@pytest.mark.asyncio
async def test_idempotency_key(db_path, patch_settings):
    patch_settings(max_concurrent_tasks=3)

    store = TaskStore(db_path)
    await store.connect()
    queue = TaskQueue(store)

    t1, start1 = await queue.enqueue("hello", idempotency_key="key-1")
    t2, start2 = await queue.enqueue("hello again", idempotency_key="key-1")

    assert t1.id == t2.id
    assert start1 is True
    assert start2 is False

    await store.disconnect()


@pytest.mark.asyncio
async def test_cancel_queued_task(db_path):
    store = TaskStore(db_path)
    await store.connect()

    task = await store.create("cancel me", status=TaskStatus.QUEUED)
    await store.update_status(task.id, TaskStatus.CANCELLED)
    loaded = await store.get(task.id)

    assert loaded is not None
    assert loaded.status == TaskStatus.CANCELLED

    await store.disconnect()


@pytest.mark.asyncio
async def test_find_by_trace(db_path):
    store = TaskStore(db_path)
    await store.connect()

    task = await store.create("trace test")
    msg = Message(
        from_agent="Planner",
        to_agent="Research",
        content="hi",
        message_type=MessageType.TASK,
        task_id=task.id,
    ).with_trace()
    await store.log_message(msg)

    found = await store.find_by_trace(msg.trace_id)
    assert len(found) == 1
    assert found[0].id == msg.id

    await store.disconnect()


@pytest.mark.asyncio
async def test_dead_letter_retry(db_path):
    outbox = MessageOutbox(db_path)
    await outbox.connect()

    msg = Message(
        from_agent="Planner",
        to_agent="Coder",
        content="retry me",
        message_type=MessageType.TASK,
    ).with_trace()
    await outbox.enqueue(msg, "agent/Coder")
    await outbox.mark_failed(msg.id)

    failed = await outbox.list_failed()
    assert len(failed) == 1

    ok = await outbox.reset_for_retry(msg.id)
    assert ok is True
    item = await outbox.get_pending_message(msg.id)
    assert item is not None

    await outbox.disconnect()
