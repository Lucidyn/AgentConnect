"""Outbox purge on startup and via API."""

import pytest

from backend.core.message_outbox import MessageOutbox
from backend.models.message import Message, MessageType


@pytest.mark.asyncio
async def test_purge_failed_removes_only_failed(db_path):
    outbox = MessageOutbox(db_path)
    await outbox.connect()

    pending = Message(
        from_agent="Planner",
        to_agent="Coder",
        content="go",
        message_type=MessageType.TASK,
    ).with_trace()
    failed = Message(
        from_agent="Planner",
        to_agent="Research",
        content="find",
        message_type=MessageType.TASK,
    ).with_trace()

    await outbox.enqueue(pending, "agent/Coder")
    await outbox.enqueue(failed, "agent/Research")
    await outbox.mark_failed(failed.id)

    removed = await outbox.purge_failed()
    assert removed == 1

    stats = await outbox.stats()
    assert stats.get("failed", 0) == 0
    assert stats.get("pending", 0) == 1

    await outbox.disconnect()


@pytest.mark.asyncio
async def test_startup_clear_failed_outbox(isolated_paths, monkeypatch):
    from backend.config import settings
    from backend.core.message_outbox import MessageOutbox
    from backend.platform import Platform

    monkeypatch.setattr(settings, "clear_failed_outbox", True)
    monkeypatch.setattr(settings, "enabled_agents", "planner,research,coder,reviewer")

    outbox = MessageOutbox(settings.tasks_db_path)
    await outbox.connect()
    msg = Message(from_agent="A", to_agent="B", content="x").with_trace()
    await outbox.enqueue(msg, "agent/B")
    await outbox.mark_failed(msg.id)
    await outbox.disconnect()

    platform = Platform()
    await platform.start()
    try:
        stats = await platform.message_outbox.stats()
        assert stats.get("failed", 0) == 0
    finally:
        await platform.stop()
