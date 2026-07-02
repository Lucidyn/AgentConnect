"""Worker process bootstrap — single agent consuming assignment stream."""

from __future__ import annotations

import asyncio
import logging

from backend.config import settings
from backend.core.agent import Agent
from backend.core.llm import LLMClient
from backend.core.message_bus import InMemoryMessageBus
from backend.core.db import create_database
from backend.core.db.schema import init_schema
from backend.core.registry import AgentRegistry
from backend.core.runtime import get_runtime
from backend.core.services import AgentServices
from backend.core.shared_memory import create_shared_memory
from backend.core.task_store import TaskStore
from backend.core.worker_runner import execute_assignment
from backend.core.worker_stream import create_worker_stream, default_consumer_name
from backend.plugins.loader import load_agent_plugins, load_tool_registry

logger = logging.getLogger(__name__)


class WorkerPlatform:
    def __init__(self, agent_name: str) -> None:
        self.agent_name = agent_name
        self.agent: Agent | None = None
        self._running = False
        self._consumer = default_consumer_name()
        self._hub = None
        self._database = None
        self._task_store = TaskStore()
        self._registry = AgentRegistry()
        self._bus = InMemoryMessageBus()

    async def start(self) -> None:
        self._database = await create_database()
        await init_schema(self._database)
        self._task_store = TaskStore(self._database)
        self._registry = AgentRegistry(self._database)
        await self._task_store.connect()
        await self._registry.connect()
        await self._bus.connect()
        self._hub = await create_worker_stream()

        agent_classes, plugin_configs = load_agent_plugins(settings.enabled_agents)
        target = next((cls for cls in agent_classes if cls.name == self.agent_name), None)
        if not target:
            raise RuntimeError(f"Worker agent '{self.agent_name}' not found in plugins")

        services = AgentServices(
            bus=self._bus,
            registry=self._registry,
            llm=LLMClient(),
            shared_memory=await create_shared_memory(),
            tools=load_tool_registry(settings.enabled_tools),
            task_store=self._task_store,
            plugin_configs=plugin_configs,
        )
        self.agent = target(services)
        runtime_name = plugin_configs.get(self.agent.name.lower(), {}).get("runtime", "native")
        await get_runtime(runtime_name).mount(self.agent)
        self._running = True
        logger.info("Worker started for agent %s (consumer=%s)", self.agent_name, self._consumer)

    async def stop(self) -> None:
        self._running = False
        if self.agent:
            runtime_name = (
                self.agent.services.plugin_configs.get(self.agent.name.lower(), {}).get(
                    "runtime", "native"
                )
            )
            await get_runtime(runtime_name).unmount(self.agent)
        if self._hub:
            await self._hub.disconnect()
        await self._bus.disconnect()
        await self._registry.disconnect()
        if self._database:
            await self._database.disconnect()
            self._database = None
        await self._task_store.disconnect()

    async def run_loop(self) -> None:
        if not self.agent or not self._hub:
            raise RuntimeError("Worker not started")
        while self._running:
            try:
                batch = await self._hub.consume_tasks(
                    consumer=self._consumer,
                    agent=self.agent_name,
                    count=1,
                    block_ms=int(settings.worker_poll_interval * 1000),
                )
                for stream_id, envelope in batch:
                    result = await execute_assignment(self.agent, envelope)
                    await self._hub.publish_result(result)
                    await self._hub.ack_task(stream_id, self._consumer)
                    logger.info(
                        "[%s] completed assignment %s success=%s",
                        self.agent_name,
                        envelope.assignment_id,
                        result.success,
                    )
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Worker loop error for %s", self.agent_name)
                await asyncio.sleep(1)
