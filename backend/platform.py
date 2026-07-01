"""Platform orchestrator — wires agents, bus, registry, memory, and tools."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Awaitable, Callable

from backend.config import settings
from backend.core.agent import Agent
from backend.core.llm import LLMClient
from backend.core.message_bus import InMemoryMessageBus, MessageBus, ReliableMessageBus, create_message_bus
from backend.core.message_outbox import MessageOutbox
from backend.core.metrics import (
    MESSAGES_SENT,
    OUTBOX_FAILED,
    OUTBOX_PENDING,
    QUEUE_ACTIVE,
    QUEUE_QUEUED,
    TASKS_FINISHED,
    TASKS_SUBMITTED,
)
from backend.core.registry import AgentRegistry
from backend.core.runtime import get_runtime
from backend.core.services import AgentServices
from backend.core.shared_memory import SharedMemory, create_shared_memory
from backend.core.task_queue import TaskQueue
from backend.core.task_store import TaskStore
from backend.models.message import Message, MessageType
from backend.models.task import TaskRecord, TaskStatus
from backend.plugins.loader import load_agent_plugins, load_tool_registry
from backend.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)


class Platform:
    def __init__(self) -> None:
        self.bus: MessageBus | None = None
        self.registry = AgentRegistry()
        self.task_store = TaskStore()
        self.message_outbox = MessageOutbox()
        self.task_queue: TaskQueue | None = None
        self.llm = LLMClient()
        self.shared_memory: SharedMemory | None = None
        self.tools = ToolRegistry()
        self.agents: dict[str, Agent] = {}
        self._agent_runtimes: dict[str, str] = {}
        self._plugin_configs: dict[str, dict] = {}
        self._message_log: list[Message] = []
        self._ws_listeners: list[Callable[[Message], Awaitable[None]]] = []
        self._running = False
        self._retry_task: asyncio.Task | None = None

    @property
    def agent_runtimes(self) -> dict[str, str]:
        return dict(self._agent_runtimes)

    async def start(self) -> None:
        if self._running:
            return

        # Re-read paths from settings on each start (supports test isolation).
        self.task_store = TaskStore()
        self.message_outbox = MessageOutbox()
        self.registry = AgentRegistry()
        self.agents.clear()
        self._agent_runtimes.clear()

        await self.registry.connect()
        await self.task_store.connect()
        await self.message_outbox.connect()
        if settings.clear_failed_outbox:
            cleared = await self.message_outbox.purge_failed()
            if cleared:
                logger.info("Cleared %d failed outbox message(s) on startup", cleared)
        self.task_queue = TaskQueue(self.task_store)
        self.bus = await create_message_bus(self.message_outbox)
        self.shared_memory = await create_shared_memory()
        self.tools = load_tool_registry(settings.enabled_tools)
        self._running = True

        if hasattr(self.bus, "add_global_listener"):
            self.bus.add_global_listener(self._on_message)  # type: ignore[union-attr]

        agent_classes, plugin_configs = load_agent_plugins(settings.enabled_agents)
        self._plugin_configs = plugin_configs

        services = AgentServices(
            bus=self.bus,
            registry=self.registry,
            llm=self.llm,
            shared_memory=self.shared_memory,
            tools=self.tools,
            task_store=self.task_store,
            on_task_finished=self._on_task_finished,
            plugin_configs=plugin_configs,
        )

        for cls in agent_classes:
            agent = cls(services)
            runtime_name = plugin_configs.get(agent.name.lower(), {}).get("runtime", "native")
            runtime = get_runtime(runtime_name)
            self.agents[agent.name] = agent
            self._agent_runtimes[agent.name] = runtime.name
            await runtime.mount(agent)

        logger.info(
            "Platform started with %d agents (runtimes: %s)",
            len(self.agents),
            self._agent_runtimes,
        )
        self._retry_task = asyncio.create_task(self._retry_loop())
        await self._bootstrap_queue()

    async def _retry_loop(self) -> None:
        while self._running:
            await asyncio.sleep(settings.message_retry_interval)
            if not isinstance(self.bus, ReliableMessageBus):
                continue
            pending = await self.message_outbox.list_retryable(
                settings.message_max_retries, settings.message_retry_grace
            )
            for message in pending:
                retries = await self.message_outbox.increment_retry(message.id)
                if retries >= settings.message_max_retries:
                    await self.message_outbox.mark_failed(message.id)
                    logger.warning("Message %s exceeded max retries", message.id)
                    continue
                logger.info("Retrying message %s (attempt %d)", message.id, retries)
                await self.bus.publish(message, track=False)

    async def _bootstrap_queue(self) -> None:
        """Recover stale tasks and fill available slots from queue."""
        await self.task_store.recover_stale_tasks()
        if not self.task_queue or not self.bus:
            return
        slots = settings.max_concurrent_tasks - await self.task_store.count_active()
        for _ in range(max(0, slots)):
            task = await self.task_store.dequeue()
            if not task:
                break
            await self.task_store.update_status(task.id, TaskStatus.SUBMITTED)
            await self._dispatch_task(task)
            logger.info("Bootstrap dispatched task %s", task.id)

    async def stop(self) -> None:
        self._running = False
        if self._retry_task:
            self._retry_task.cancel()
            try:
                await self._retry_task
            except asyncio.CancelledError:
                pass
        for agent in self.agents.values():
            runtime_name = self._agent_runtimes.get(agent.name, "native")
            await get_runtime(runtime_name).unmount(agent)
        if self.bus:
            await self.bus.disconnect()
        if self.shared_memory:
            await self.shared_memory.disconnect()
        await self.task_store.disconnect()
        await self.registry.disconnect()
        if self.message_outbox:
            await self.message_outbox.disconnect()

    async def _on_task_finished(self, task_id: str) -> None:
        if not self.task_queue or not self.bus:
            return
        next_task = await self.task_queue.on_task_finished(task_id)
        if next_task:
            await self._dispatch_task(next_task)

    async def _dispatch_task(self, task: TaskRecord) -> Message:
        assert self.task_queue and self.bus
        message = await self.task_queue.build_start_message(task)
        message.with_trace()
        await self.bus.publish(message)
        await self.task_store.log_message(message)
        return message

    async def _on_message(self, message: Message) -> None:
        self._message_log.append(message)
        if message.task_id:
            await self.task_store.log_message(message)
        for listener in self._ws_listeners:
            try:
                await listener(message)
            except Exception:
                logger.exception("WebSocket listener error")

    def add_message_listener(self, listener: Callable[[Message], Awaitable[None]]) -> None:
        self._ws_listeners.append(listener)

    def remove_message_listener(self, listener: Callable[[Message], Awaitable[None]]) -> None:
        if listener in self._ws_listeners:
            self._ws_listeners.remove(listener)

    @property
    def message_log(self) -> list[Message]:
        if isinstance(self.bus, (InMemoryMessageBus, ReliableMessageBus)):
            return self.bus.history  # type: ignore[union-attr]
        return self._message_log

    async def submit_task(
        self,
        user_input: str,
        idempotency_key: str = "",
        *,
        template_id: str = "",
        custom_plan: dict | None = None,
        collaboration_mode: str = "",
        negotiation: bool | None = None,
    ) -> tuple[TaskRecord, Message | None]:
        if not self.bus or not self.task_queue:
            raise RuntimeError("Platform not started")

        key = idempotency_key.strip() or None
        task, should_start = await self.task_queue.enqueue(user_input, idempotency_key=key)

        ctx_updates: dict = {}
        if template_id:
            ctx_updates["template_id"] = template_id
            from backend.core.plan_templates import get_template

            template = get_template(template_id)
            if template:
                ctx_updates.setdefault("collaboration_mode", template.collaboration_mode)
                ctx_updates.setdefault("negotiation", template.negotiation)
        if custom_plan:
            ctx_updates["custom_plan"] = custom_plan
        if collaboration_mode:
            ctx_updates["collaboration_mode"] = collaboration_mode
        if negotiation is not None:
            ctx_updates["negotiation"] = negotiation

        if ctx_updates:
            ctx = dict(task.context or {})
            ctx.update(ctx_updates)
            if ctx.get("negotiation"):
                from backend.config import settings

                ns = dict(ctx.get("negotiation_state") or {})
                ns.setdefault("max_rounds", settings.negotiation_max_rounds)
                ctx["negotiation_state"] = ns
            await self.task_store.save_context(task.id, ctx)
            task = await self.task_store.get(task.id) or task

        TASKS_SUBMITTED.inc()
        if not should_start:
            return task, None

        message = await self._dispatch_task(task)
        return task, message

    async def refresh_metrics(self) -> None:
        QUEUE_ACTIVE.set(await self.task_store.count_active())
        QUEUE_QUEUED.set(await self.task_store.count_queued())
        stats = await self.message_outbox.stats()
        OUTBOX_PENDING.set(stats.get("pending", 0))
        OUTBOX_FAILED.set(stats.get("failed", 0))

    async def approve_task(self, task_id: str, action: str) -> TaskRecord | None:
        task = await self.task_store.get(task_id)
        if not task or task.status != TaskStatus.WAITING_APPROVAL:
            return None
        if not self.bus:
            return None
        if action not in ("approve", "reject", "retry"):
            return None

        ctx = task.context or {}
        message = Message(
            from_agent="User",
            to_agent="Planner",
            content=f"approval:{action}",
            message_type=MessageType.STATUS,
            task_id=task_id,
            metadata={
                "approval_action": action,
                "assignment_id": ctx.get("approval_assignment_id", ""),
            },
        ).with_trace()
        await self.bus.publish(message)
        await self.task_store.log_message(message)
        return await self.task_store.get(task_id)

    async def cancel_task(self, task_id: str) -> TaskRecord | None:
        task = await self.task_store.get(task_id)
        if not task:
            return None
        if task.status in (TaskStatus.COMPLETED, TaskStatus.CANCELLED):
            return task

        was_active = task.status in (
            TaskStatus.SUBMITTED,
            TaskStatus.PLANNING,
            TaskStatus.RUNNING,
            TaskStatus.WAITING_APPROVAL,
        )
        await self.task_store.update_status(task_id, TaskStatus.CANCELLED)
        if was_active:
            await self._on_task_finished(task_id)
        return await self.task_store.get(task_id)

    async def retry_dead_letter(self, message_id: str) -> bool:
        if not isinstance(self.bus, ReliableMessageBus):
            return False
        if not await self.message_outbox.reset_for_retry(message_id):
            return False
        item = await self.message_outbox.get_pending_message(message_id)
        if not item:
            return False
        message, _channel = item
        await self.bus.publish(message, track=False)
        return True

    async def purge_dead_letters(self) -> int:
        return await self.message_outbox.purge_failed()


platform = Platform()
