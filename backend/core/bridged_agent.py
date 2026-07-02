"""Bridged agents — connect external SDKs to the platform message bus."""

from __future__ import annotations

import logging
from abc import abstractmethod
from typing import Any

from backend.constants import PLANNER
from backend.core.agent import Agent
from backend.models.message import Message, MessageType

logger = logging.getLogger(__name__)


class OpenAIAgentsBridge(Agent):
    """Delegate think() to OpenAI Agents SDK (pip install openai-agents)."""

    instructions: str = "You are a helpful assistant."

    def build_sdk_agent(self) -> Any:
        from agents import Agent as SDKAgent

        model = self.plugin_config.get("model")
        kwargs: dict[str, Any] = {"name": self.name, "instructions": self.instructions}
        if model:
            kwargs["model"] = model
        return SDKAgent(**kwargs)

    async def think(self, message: Message) -> str | None:
        if message.from_agent not in (PLANNER, "User"):
            return None
        if message.message_type == MessageType.ERROR:
            return None

        try:
            from agents import Runner

            sdk_agent = self.build_sdk_agent()
            result = await Runner.run(sdk_agent, message.content)
            output = getattr(result, "final_output", None) or getattr(result, "output", "")
            text = str(output) if output else f"[{self.name}] completed with no output"
        except ImportError:
            logger.warning("[%s] openai-agents not installed, using fallback", self.name)
            text = self._fallback(message)
        except Exception as exc:
            logger.warning("[%s] OpenAI Agents run failed: %s", self.name, exc)
            text = self._fallback(message)

        if message.from_agent == PLANNER:
            await self.reply_to_planner(message, text)
            return None
        return text

    def _fallback(self, message: Message) -> str:
        return (
            f"[{self.name} · openai-agents fallback]\n"
            f"Received: {message.content[:300]}\n"
            f"(Install openai-agents + set OPENAI_API_KEY for live runs)"
        )


class LangGraphBridge(Agent):
    """Delegate think() to a compiled LangGraph (pip install langgraph)."""

    def __init__(self, services) -> None:
        super().__init__(services)
        self._compiled_graph: Any | None = None

    @abstractmethod
    async def build_graph(self) -> Any:
        """Return a compiled LangGraph with ainvoke support."""

    async def _get_graph(self) -> Any:
        if self._compiled_graph is None:
            self._compiled_graph = await self.build_graph()
        return self._compiled_graph

    async def think(self, message: Message) -> str | None:
        if message.from_agent not in (PLANNER, "User"):
            return None
        if message.message_type == MessageType.ERROR:
            return None

        try:
            graph = await self._get_graph()
            state = await graph.ainvoke({"input": message.content})
            if isinstance(state, dict):
                text = state.get("output") or state.get("result") or str(state)
            else:
                text = str(state)
        except ImportError:
            logger.warning("[%s] langgraph not installed, using fallback", self.name)
            text = self._fallback(message)
        except Exception as exc:
            logger.warning("[%s] LangGraph run failed: %s", self.name, exc)
            text = self._fallback(message)

        if message.from_agent == PLANNER:
            await self.reply_to_planner(message, text)
            return None
        return text

    def _fallback(self, message: Message) -> str:
        return (
            f"[{self.name} · langgraph fallback]\n"
            f"Received: {message.content[:300]}\n"
            f"(Install langgraph for live graph runs)"
        )
