"""Agent message deduplication persisted in task context."""

import asyncio

import pytest

from backend.core.agent import Agent
from backend.core.message_bus import InMemoryMessageBus
from backend.core.registry import AgentRegistry
from backend.core.services import AgentServices
from backend.core.shared_memory import InMemorySharedMemory
from backend.core.task_store import TaskStore
from backend.core.llm import LLMClient
from backend.models.message import Message, MessageType
from backend.models.task import TaskStatus
from backend.tools.registry import ToolRegistry


class EchoAgent(Agent):
    name = "Echo"
    role = "echo"
    capabilities = ["echo"]
    think_count = 0

    async def think(self, message: Message) -> str | None:
        EchoAgent.think_count += 1
        return f"echo:{message.content}"


class FailingAgent(Agent):
    name = "Failing"
    role = "test"
    capabilities = ["fail"]

    async def think(self, message: Message) -> str | None:
        raise RuntimeError("boom")


@pytest.mark.asyncio
async def test_mark_message_processed_persists(db_path):
    store = TaskStore(db_path)
    await store.connect()
    task = await store.create("dedup", status=TaskStatus.RUNNING)

    assert not await store.is_message_processed(task.id, "msg-1")
    await store.mark_message_processed(task.id, "msg-1")
    assert await store.is_message_processed(task.id, "msg-1")

    reloaded = await store.get(task.id)
    assert reloaded.context.get("processed_message_ids") == ["msg-1"]
    await store.disconnect()


@pytest.mark.asyncio
async def test_agent_dedup_survives_memory_reset(isolated_paths):
    EchoAgent.think_count = 0

    registry = AgentRegistry(isolated_paths["registry"])
    await registry.connect()
    store = TaskStore(isolated_paths["tasks"])
    await store.connect()
    task = await store.create("dedup agent", status=TaskStatus.RUNNING)

    bus = InMemoryMessageBus()
    await bus.connect()
    services = AgentServices(
        bus=bus,
        registry=registry,
        llm=LLMClient(),
        shared_memory=InMemorySharedMemory(),
        tools=ToolRegistry(),
        task_store=store,
    )

    msg = Message(
        from_agent="User",
        to_agent="Echo",
        content="hello",
        message_type=MessageType.TASK,
        task_id=task.id,
    ).with_trace()

    agent = EchoAgent(services)
    await agent.register()
    await agent.start()
    await bus.publish(msg)
    await asyncio.sleep(0.15)
    assert EchoAgent.think_count == 1
    await agent.stop()

    agent2 = EchoAgent(services)
    await agent2.register()
    await agent2.start()
    await bus.publish(msg)
    await asyncio.sleep(0.15)
    assert EchoAgent.think_count == 1

    await agent2.stop()
    await bus.disconnect()
    await store.disconnect()
    await registry.disconnect()


@pytest.mark.asyncio
async def test_failed_message_is_not_marked_processed(isolated_paths):
    registry = AgentRegistry(isolated_paths["registry"])
    await registry.connect()
    store = TaskStore(isolated_paths["tasks"])
    await store.connect()
    task = await store.create("fail agent", status=TaskStatus.RUNNING)

    bus = InMemoryMessageBus()
    await bus.connect()
    services = AgentServices(
        bus=bus,
        registry=registry,
        llm=LLMClient(),
        shared_memory=InMemorySharedMemory(),
        tools=ToolRegistry(),
        task_store=store,
    )

    agent = FailingAgent(services)
    await agent.register()
    await agent.start()

    msg = Message(
        from_agent="User",
        to_agent="Failing",
        content="hello",
        message_type=MessageType.TASK,
        task_id=task.id,
    ).with_trace()
    await bus.publish(msg)
    await asyncio.sleep(0.15)

    assert not await store.is_message_processed(task.id, msg.id)

    await agent.stop()
    await bus.disconnect()
    await store.disconnect()
    await registry.disconnect()
