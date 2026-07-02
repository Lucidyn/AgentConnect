"""Runtime adapter tests."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.core.agent import Agent
from backend.core.runtime import NativeRuntime, get_runtime, list_runtimes
from backend.core.services import AgentServices
from backend.models.message import Message


class _EchoAgent(Agent):
    name = "Echo"
    role = "test"
    capabilities = ["echo"]
    description = "test"

    async def think(self, message: Message) -> str | None:
        return message.content


@pytest.mark.asyncio
async def test_get_runtime():
    assert get_runtime("native").name == "native"
    assert get_runtime("openai_agents").name == "openai_agents"
    assert get_runtime("langgraph").name == "langgraph"
    assert get_runtime("unknown").name == "native"
    assert "native" in list_runtimes()


@pytest.mark.asyncio
async def test_openai_agents_bridge_fallback():
    from plugins.openai_agents.summarizer import SummarizerAgent

    agent = SummarizerAgent(AgentServices(bus=None, registry=None, llm=None, shared_memory=None, tools=None))  # type: ignore[arg-type]
    msg = Message(from_agent="User", to_agent="Summarizer", content="summarize this task")
    result = await agent.think(msg)
    assert result is not None
    assert "fallback" in result or "bullet" in result.lower() or "Summarizer" in result


@pytest.mark.asyncio
async def test_langgraph_bridge_fallback():
    from plugins.langgraph.router import RouterAgent

    agent = RouterAgent(AgentServices(bus=None, registry=None, llm=None, shared_memory=None, tools=None))  # type: ignore[arg-type]
    msg = Message(from_agent="User", to_agent="Router", content="build an OCR image service")
    result = await agent.think(msg)
    assert result is not None
    assert "fallback" in result or "Route" in result or "vision" in result


@pytest.mark.asyncio
async def test_native_runtime_mount():
    bus = MagicMock()
    bus.subscribe = AsyncMock()
    bus.unsubscribe = AsyncMock()
    bus.replay_channel = AsyncMock(return_value=0)

    registry = MagicMock()
    registry.register = AsyncMock()
    registry.update_status = AsyncMock()

    services = AgentServices(
        bus=bus, registry=registry, llm=MagicMock(), shared_memory=MagicMock(), tools=MagicMock()
    )
    agent = _EchoAgent(services)
    runtime = NativeRuntime()
    await runtime.mount(agent)
    assert agent._running is True
    await runtime.unmount(agent)
    assert agent._running is False
