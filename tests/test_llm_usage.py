"""LLM usage tracking tests."""

import pytest

from backend.core.llm_usage import LLMUsageEntry, estimate_cost, merge_usage
from backend.models.task_context import TaskContext


def test_merge_usage_totals():
    entries = [
        LLMUsageEntry(agent="Coder", prompt_tokens=100, completion_tokens=50, total_tokens=150),
        LLMUsageEntry(agent="Writer", prompt_tokens=200, completion_tokens=80, total_tokens=280),
    ]
    totals = merge_usage(entries)
    assert totals["prompt_tokens"] == 300
    assert totals["completion_tokens"] == 130
    assert totals["total_tokens"] == 430
    assert totals["calls"] == 2


def test_estimate_cost():
    cost = estimate_cost(
        {"prompt_tokens": 1000, "completion_tokens": 500},
        input_per_1k=0.001,
        output_per_1k=0.002,
    )
    assert cost == pytest.approx(0.002)


@pytest.mark.asyncio
async def test_llm_chat_records_usage(db_path):
    from backend.agents.research import ResearchAgent
    from backend.core.llm import LLMClient
    from backend.core.message_bus import InMemoryMessageBus
    from backend.core.registry import AgentRegistry
    from backend.core.services import AgentServices
    from backend.core.shared_memory import InMemorySharedMemory
    from backend.core.task_store import TaskStore
    from backend.models.message import Message, MessageType
    from backend.tools.registry import ToolRegistry

    store = TaskStore(db_path)
    await store.connect()
    task = await store.create("token test")
    recorded: list = []

    async def record_usage(task_id: str, agent: str, entry) -> None:
        recorded.append((task_id, agent, entry))

    registry = AgentRegistry(db_path.replace("tasks", "registry"))
    await registry.connect()
    bus = InMemoryMessageBus()
    await bus.connect()
    services = AgentServices(
        bus=bus,
        registry=registry,
        llm=LLMClient(),
        shared_memory=InMemorySharedMemory(),
        tools=ToolRegistry(),
        task_store=store,
        record_llm_usage=record_usage,
    )
    agent = ResearchAgent(services)
    await agent.register()
    await agent.start()
    agent._current_task_id = task.id

    async def fake_chat(*args, **kwargs):
        kwargs.setdefault("agent", "")
        kwargs.setdefault("on_usage", None)
        if kwargs.get("on_usage") and kwargs.get("agent"):
            from backend.core.llm_usage import LLMUsageEntry

            await kwargs["on_usage"](
                LLMUsageEntry(
                    agent=kwargs["agent"],
                    prompt_tokens=10,
                    completion_tokens=5,
                    total_tokens=15,
                    model="test",
                )
            )
        return "ok"

    services.llm.chat = fake_chat  # type: ignore[method-assign]
    msg = Message(
        from_agent="Planner",
        to_agent="Research",
        content="调研 YOLO",
        message_type=MessageType.TASK,
        task_id=task.id,
    )
    await agent.think(msg)
    await agent.stop()
    await bus.disconnect()
    await registry.disconnect()
    await store.disconnect()

    assert recorded
    assert recorded[0][1] == "Research"
    assert recorded[0][2].total_tokens == 15


@pytest.mark.asyncio
async def test_task_context_stores_llm_usage(db_path):
    from backend.core.task_store import TaskStore

    store = TaskStore(db_path)
    await store.connect()
    task = await store.create("usage test")
    ctx = TaskContext(
        llm_usage=[
            LLMUsageEntry(agent="Planner", prompt_tokens=10, completion_tokens=5, total_tokens=15)
        ]
    )
    await store.save_context(task.id, ctx.model_dump(mode="json"))
    loaded = await store.get(task.id)
    saved = TaskContext.model_validate(loaded.context or {})
    assert len(saved.llm_usage) == 1
    assert saved.llm_usage[0].agent == "Planner"
    await store.disconnect()
