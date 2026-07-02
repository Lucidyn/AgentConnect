"""Platform orchestrator — wires agents, bus, registry, memory, and tools."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Awaitable, Callable

from backend.config import settings
from backend.constants import PLANNER
from backend.core.agent import Agent
from backend.core.llm import LLMClient
from backend.core.message_bus import InMemoryMessageBus, MessageBus, ReliableMessageBus, create_message_bus
from backend.core.db import create_database
from backend.core.db.schema import init_audit_schema, init_schema
from backend.core.message_outbox import MessageOutbox
from backend.core.replica import get_replica_id
from backend.core.metrics import (
    MESSAGES_SENT,
    OUTBOX_FAILED,
    OUTBOX_PENDING,
    QUEUE_ACTIVE,
    QUEUE_QUEUED,
    TASKS_FINISHED,
    TASKS_SUBMITTED,
)
from backend.core.stream_buffer import StreamBuffer
from backend.core.registry import AgentRegistry
from backend.core.runtime import get_runtime
from backend.core.services import AgentServices
from backend.core.shared_memory import SharedMemory, create_shared_memory
from backend.core.task_queue import TaskQueue
from backend.core.task_store import TaskStore
from backend.core.tenant_store import TenantStore
from backend.models.auth import DEFAULT_TENANT_ID
from backend.core.worker_dispatcher import WorkerDispatcher
from backend.core.worker_stream import create_worker_stream, default_consumer_name, parse_remote_agents
from backend.models.message import Message, MessageIntent, MessageType
from backend.models.task import TaskRecord, TaskStatus
from backend.models.task_context import TaskContext
from backend.models.plan import TaskPlan
from backend.core.llm_usage import LLMUsageEntry
from backend.plugins.loader import load_agent_plugins, load_mcp_tools, load_tool_registry
from backend.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)


class Platform:
    def __init__(self) -> None:
        self.bus: MessageBus | None = None
        self.registry = AgentRegistry()
        self.task_store = TaskStore()
        self.tenant_store: TenantStore | None = None
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
        self._result_task: asyncio.Task | None = None
        self._worker_hub = None
        self._remote_agents: set[str] = set()
        self._result_consumer = default_consumer_name()
        self._database = None
        self.stream_buffer = StreamBuffer()
        self.audit_log = None

    @property
    def agent_runtimes(self) -> dict[str, str]:
        return dict(self._agent_runtimes)

    async def start(self) -> None:
        if self._running:
            return

        # Re-read paths from settings on each start (supports test isolation).
        self._database = await create_database()
        await init_schema(self._database)
        await init_audit_schema(self._database)
        from backend.core.audit_log import AuditLog

        self.audit_log = AuditLog(self._database)
        self.tenant_store = TenantStore(self._database)
        if settings.multi_tenant:
            await self.tenant_store.ensure_default_tenant()
        self.task_store = TaskStore(self._database)
        self.message_outbox = MessageOutbox(self._database)
        self.registry = AgentRegistry(self._database)
        self.agents.clear()
        self._agent_runtimes.clear()

        await self.registry.connect()
        if settings.clear_failed_outbox:
            cleared = await self.message_outbox.purge_failed()
            if cleared:
                logger.info("Cleared %d failed outbox message(s) on startup", cleared)
        self.task_queue = TaskQueue(self.task_store)
        self.bus = await create_message_bus(self.message_outbox)
        self.shared_memory = await create_shared_memory()
        self.tools = load_tool_registry(settings.enabled_tools)
        mcp_count = await load_mcp_tools(self.tools)
        if mcp_count:
            logger.info("Loaded %d MCP tool(s)", mcp_count)
        self._running = True

        if hasattr(self.bus, "add_global_listener"):
            self.bus.add_global_listener(self._on_message)  # type: ignore[union-attr]

        agent_classes, plugin_configs = load_agent_plugins(settings.enabled_agents)
        self._plugin_configs = plugin_configs
        agent_names = [cls.name for cls in agent_classes]
        self._remote_agents = parse_remote_agents(agent_names)

        worker_hub = None
        worker_dispatcher = None
        if settings.distributed_workers:
            worker_hub = await create_worker_stream()
            self._worker_hub = worker_hub
            worker_dispatcher = WorkerDispatcher(worker_hub, self._remote_agents)
            logger.info(
                "Distributed workers enabled — remote agents: %s",
                sorted(self._remote_agents),
            )

        mount_classes = agent_classes
        if settings.distributed_workers:
            mount_classes = [
                cls
                for cls in agent_classes
                if cls.name == PLANNER or cls.name not in self._remote_agents
            ]

        services = AgentServices(
            bus=self.bus,
            registry=self.registry,
            llm=self.llm,
            shared_memory=self.shared_memory,
            tools=self.tools,
            task_store=self.task_store,
            on_task_finished=self._on_task_finished,
            record_llm_usage=self._record_llm_usage,
            plugin_configs=plugin_configs,
            worker_hub=worker_hub,
            worker_dispatcher=worker_dispatcher,
            stream_buffer=self.stream_buffer,
            agents=self.agents,
        )

        for cls in mount_classes:
            agent = cls(services)
            runtime_name = plugin_configs.get(agent.name.lower(), {}).get("runtime", "native")
            runtime = get_runtime(runtime_name)
            self.agents[agent.name] = agent
            self._agent_runtimes[agent.name] = runtime.name
            await runtime.mount(agent)

        logger.info(
            "Platform started with %d agents (runtimes: %s, distributed=%s, replica=%s, db=%s)",
            len(self.agents),
            self._agent_runtimes,
            settings.distributed_workers,
            get_replica_id(),
            "postgres" if self._database and self._database.is_postgres else "sqlite",
        )
        self._retry_task = asyncio.create_task(self._retry_loop())
        if settings.distributed_workers and self._worker_hub:
            self._result_task = asyncio.create_task(self._worker_result_loop())
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

    async def _worker_result_loop(self) -> None:
        """Consume worker results and inject into Planner via message bus."""
        hub = self._worker_hub
        if not hub or not self.bus:
            return
        while self._running:
            try:
                batch = await hub.consume_results(
                    consumer=self._result_consumer,
                    count=10,
                    block_ms=1000,
                )
                for stream_id, result in batch:
                    await self._inject_worker_result(result)
                    await hub.ack_result(stream_id, self._result_consumer)
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Worker result loop error")
                await asyncio.sleep(1)

    async def _inject_worker_result(self, result) -> None:
        from backend.core.worker_protocol import WorkerResultEnvelope

        assert isinstance(result, WorkerResultEnvelope)
        assert self.bus
        if result.success:
            message = Message(
                from_agent=result.agent,
                to_agent=PLANNER,
                content=result.content,
                message_type=MessageType.RESPONSE,
                task_id=result.task_id,
                trace_id=result.task_id,
                metadata={
                    "intent": MessageIntent.ASSIGNMENT_RESULT.value,
                    "assignment_id": result.assignment_id,
                    "attempt": result.metadata.get("attempt", 0),
                    "worker_envelope_id": result.envelope_id,
                },
            )
        else:
            message = Message(
                from_agent=result.agent,
                to_agent=PLANNER,
                content=result.error or "worker error",
                message_type=MessageType.ERROR,
                task_id=result.task_id,
                trace_id=result.task_id,
                metadata={
                    "intent": MessageIntent.ASSIGNMENT_ERROR.value,
                    "assignment_id": result.assignment_id,
                    "attempt": result.metadata.get("attempt", 0),
                    "worker_envelope_id": result.envelope_id,
                },
            )
        message.with_trace()
        await self.bus.publish(message)
        await self.task_store.log_message(message)

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
        if self._result_task:
            self._result_task.cancel()
            try:
                await self._result_task
            except asyncio.CancelledError:
                pass
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
        if self._database:
            await self._database.disconnect()
            self._database = None
        if self._worker_hub:
            await self._worker_hub.disconnect()
            self._worker_hub = None

    async def _on_task_finished(self, task_id: str) -> None:
        await self.stream_buffer.finish(task_id)
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
        merged: list[Message] = []
        seen: set[str] = set()
        sources: list[Message] = []
        if isinstance(self.bus, (InMemoryMessageBus, ReliableMessageBus)):
            sources.extend(self.bus.history)  # type: ignore[union-attr]
        sources.extend(self._message_log)
        for message in sources:
            if message.id in seen:
                continue
            seen.add(message.id)
            merged.append(message)
        return merged

    async def _record_llm_usage(self, task_id: str, agent: str, entry: LLMUsageEntry) -> None:
        task = await self.task_store.get(task_id)
        if not task:
            return
        ctx = TaskContext.model_validate(task.context or {})
        ctx.llm_usage.append(entry)
        await self.task_store.save_context(task_id, ctx.model_dump(mode="json"))
        if self.tenant_store:
            from backend.core.budget import record_usage_spend

            await record_usage_spend(self.tenant_store, task.tenant_id, entry)

    async def _audit(
        self,
        *,
        tenant_id: str,
        actor: str,
        action: str,
        task_id: str = "",
        detail: dict | None = None,
    ) -> None:
        if not self.audit_log:
            return
        await self.audit_log.record(
            tenant_id=tenant_id,
            actor=actor,
            action=action,
            task_id=task_id,
            detail=detail,
        )

    async def submit_task(
        self,
        user_input: str,
        idempotency_key: str = "",
        *,
        tenant_id: str = DEFAULT_TENANT_ID,
        template_id: str = "",
        custom_plan: dict | None = None,
        collaboration_mode: str = "",
        negotiation: bool | None = None,
    ) -> tuple[TaskRecord, Message | None]:
        if not self.bus or not self.task_queue:
            raise RuntimeError("Platform not started")

        if self.tenant_store:
            from backend.core.budget import check_submit_budget

            budget_err = await check_submit_budget(self.tenant_store, tenant_id)
            if budget_err:
                raise ValueError(budget_err)

        key = idempotency_key.strip() or None
        task, should_start = await self.task_queue.enqueue(
            user_input, idempotency_key=key, tenant_id=tenant_id
        )

        ctx_updates: dict = {}
        if template_id:
            ctx_updates["template_id"] = template_id
        if custom_plan:
            ctx_updates["custom_plan"] = custom_plan
        if collaboration_mode:
            ctx_updates["collaboration_mode"] = collaboration_mode
        else:
            ctx_updates.setdefault("collaboration_mode", "planner")
        if negotiation is not None:
            ctx_updates["negotiation"] = negotiation
        else:
            ctx_updates.setdefault("negotiation", False)

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

        TASKS_SUBMITTED.labels(tenant_id=tenant_id).inc()
        if not should_start:
            return task, None

        message = await self._dispatch_task(task)
        await self._audit(
            tenant_id=tenant_id,
            actor="operator",
            action="task.submit",
            task_id=task.id,
            detail={"input_preview": user_input[:120]},
        )
        return task, message

    async def refresh_metrics(self) -> None:
        QUEUE_ACTIVE.set(await self.task_store.count_active())
        QUEUE_QUEUED.set(await self.task_store.count_queued())
        stats = await self.message_outbox.stats()
        OUTBOX_PENDING.set(stats.get("pending", 0))
        OUTBOX_FAILED.set(stats.get("failed", 0))

    async def approve_task(
        self, task_id: str, action: str, tenant_id: str | None = None
    ) -> TaskRecord | None:
        task = await self.task_store.get(task_id, tenant_id=tenant_id)
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
        await self._audit(
            tenant_id=task.tenant_id,
            actor="operator",
            action=f"task.approve.{action}",
            task_id=task_id,
            detail={"assignment_id": ctx.get("approval_assignment_id", "")},
        )
        return await self.task_store.get(task_id, tenant_id=tenant_id)

    async def resume_task(
        self, task_id: str, from_assignment: str = "", tenant_id: str | None = None
    ) -> TaskRecord | None:
        task = await self.task_store.get(task_id, tenant_id=tenant_id)
        if not task or not self.bus:
            return None
        if task.status not in (
            TaskStatus.FAILED,
            TaskStatus.RUNNING,
            TaskStatus.PLANNING,
            TaskStatus.WAITING_APPROVAL,
        ):
            return None

        await self.task_store.update_status(task_id, TaskStatus.RUNNING)
        message = Message(
            from_agent="User",
            to_agent=PLANNER,
            content="resume",
            message_type=MessageType.TASK,
            task_id=task_id,
            metadata={"resume_from": from_assignment} if from_assignment else {},
        ).with_trace()
        await self.bus.publish(message)
        await self.task_store.log_message(message)
        await self._audit(
            tenant_id=task.tenant_id,
            actor="operator",
            action="task.resume",
            task_id=task_id,
            detail={"from_assignment": from_assignment},
        )
        return await self.task_store.get(task_id, tenant_id=tenant_id)

    async def replay_task(
        self,
        task_id: str,
        *,
        checkpoint_id: str = "",
        from_assignment: str = "",
        tenant_id: str | None = None,
    ) -> TaskRecord | None:
        task = await self.task_store.get(task_id, tenant_id=tenant_id)
        if not task or not self.bus:
            return None

        ctx = TaskContext.model_validate(task.context or {})
        plan = TaskPlan.from_record(task.plan) if task.plan else None
        if not plan:
            return None

        target_assignment = from_assignment
        if checkpoint_id:
            from backend.core.checkpoints import find_checkpoint

            snapshot = find_checkpoint(ctx, checkpoint_id)
            if not snapshot:
                return None
            plan = TaskPlan.from_record(snapshot.plan) or plan
            ctx.results = dict(snapshot.results)
            target_assignment = snapshot.assignment_id

        if target_assignment:
            reset_ids = plan.reset_from_assignment(target_assignment, cascade=True)
            for reset_id in reset_ids:
                ctx.results.pop(reset_id, None)

        await self.task_store.save_plan(task_id, plan.to_context())
        await self.task_store.save_context(task_id, ctx.model_dump(mode="json"))
        await self.task_store.update_status(task_id, TaskStatus.RUNNING)

        message = Message(
            from_agent="User",
            to_agent=PLANNER,
            content="replay",
            message_type=MessageType.TASK,
            task_id=task_id,
            metadata={"resume_from": target_assignment, "replay": True},
        ).with_trace()
        await self.bus.publish(message)
        await self.task_store.log_message(message)
        await self._audit(
            tenant_id=task.tenant_id,
            actor="operator",
            action="task.replay",
            task_id=task_id,
            detail={"checkpoint_id": checkpoint_id, "from_assignment": target_assignment},
        )
        return await self.task_store.get(task_id, tenant_id=tenant_id)

    async def cancel_task(self, task_id: str, tenant_id: str | None = None) -> TaskRecord | None:
        task = await self.task_store.get(task_id, tenant_id=tenant_id)
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
