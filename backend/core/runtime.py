"""Agent runtime registry — native, OpenAI Agents SDK, LangGraph."""

from __future__ import annotations

import logging
from typing import Protocol

from backend.core.agent import Agent
from backend.core.bridged_agent import LangGraphBridge, OpenAIAgentsBridge

logger = logging.getLogger(__name__)


class AgentRuntime(Protocol):
    name: str

    async def mount(self, agent: Agent) -> Agent: ...
    async def unmount(self, agent: Agent) -> None: ...


class NativeRuntime:
    """Default: agent inbox loop via register() + start()."""

    name = "native"

    async def mount(self, agent: Agent) -> Agent:
        await agent.register()
        await agent.start()
        return agent

    async def unmount(self, agent: Agent) -> None:
        await agent.stop()


class OpenAIAgentsRuntime(NativeRuntime):
    """Validates OpenAIAgentsBridge, then mounts like native."""

    name = "openai_agents"

    async def mount(self, agent: Agent) -> Agent:
        if not isinstance(agent, OpenAIAgentsBridge):
            logger.warning(
                "Agent %s uses runtime=openai_agents but is not OpenAIAgentsBridge",
                agent.name,
            )
        return await super().mount(agent)


class LangGraphRuntime(NativeRuntime):
    """Validates LangGraphBridge, then mounts like native."""

    name = "langgraph"

    async def mount(self, agent: Agent) -> Agent:
        if not isinstance(agent, LangGraphBridge):
            logger.warning(
                "Agent %s uses runtime=langgraph but is not LangGraphBridge",
                agent.name,
            )
        return await super().mount(agent)


_RUNTIMES: dict[str, AgentRuntime] = {
    "native": NativeRuntime(),
    "openai_agents": OpenAIAgentsRuntime(),
    "langgraph": LangGraphRuntime(),
}


def get_runtime(name: str = "native") -> AgentRuntime:
    key = (name or "native").lower().replace("-", "_")
    runtime = _RUNTIMES.get(key)
    if not runtime:
        logger.warning("Unknown runtime '%s', falling back to native", name)
        return _RUNTIMES["native"]
    return runtime


def list_runtimes() -> list[str]:
    return list(_RUNTIMES.keys())
