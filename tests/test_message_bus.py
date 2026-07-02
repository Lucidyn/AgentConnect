"""Message bus and reliable outbox tests."""

import pytest

from backend.core.message_bus import InMemoryMessageBus, ReliableMessageBus
from backend.core.message_outbox import MessageOutbox
from backend.models.message import Message, MessageType


@pytest.mark.asyncio
async def test_reliable_bus_enqueue_and_ack(db_path):
    outbox = MessageOutbox(db_path)
    await outbox.connect()
    inner = InMemoryMessageBus()
    await inner.connect()
    bus = ReliableMessageBus(inner, outbox)

    received: list[Message] = []

    async def handler(msg: Message) -> None:
        received.append(msg)

    await bus.subscribe("agent/Coder", handler)

    msg = Message(
        from_agent="Planner",
        to_agent="Coder",
        content="implement",
        message_type=MessageType.TASK,
        task_id="task-1",
    ).with_trace()
    await bus.publish(msg)

    await __import__("asyncio").sleep(0.05)
    assert len(received) == 1
    pending = await outbox.pending_for_channel("agent/Coder")
    assert len(pending) == 1

    await bus.ack(msg.id)
    pending = await outbox.pending_for_channel("agent/Coder")
    assert len(pending) == 0

    await bus.disconnect()


@pytest.mark.asyncio
async def test_reliable_bus_retry_without_duplicate_enqueue(db_path):
    outbox = MessageOutbox(db_path)
    await outbox.connect()
    inner = InMemoryMessageBus()
    await inner.connect()
    bus = ReliableMessageBus(inner, outbox)

    msg = Message(
        from_agent="Planner",
        to_agent="Research",
        content="research",
        message_type=MessageType.TASK,
    ).with_trace()
    await bus.publish(msg)
    await bus.publish(msg, track=False)

    stats = await outbox.stats()
    assert stats.get("pending", 0) == 1

    await bus.disconnect()


@pytest.mark.asyncio
async def test_inmemory_bus_delivers_to_subscriber():
    bus = InMemoryMessageBus()
    await bus.connect()
    inbox: list[Message] = []

    async def handler(msg: Message) -> None:
        inbox.append(msg)

    await bus.subscribe("agent/Planner", handler)
    msg = Message(from_agent="User", to_agent="Planner", content="hi")
    await bus.publish(msg)

    await __import__("asyncio").sleep(0.05)
    assert len(inbox) == 1
    assert inbox[0].content == "hi"

    await bus.disconnect()
