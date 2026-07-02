"""Base Agent — inbox, outbox, memory, send/receive/think lifecycle."""

from __future__ import annotations

import asyncio
import logging
import time
from abc import ABC, abstractmethod
from typing import Any

from backend.config import settings
from backend.constants import MAX_PROCESSED_MESSAGE_IDS, PLANNER
from backend.core.metrics import AGENT_THINK_SECONDS, MESSAGES_SENT
from backend.core.services import AgentServices
from backend.core.trace import log_event
from backend.core.llm_usage import LLMUsageEntry
from backend.models.auth import DEFAULT_TENANT_ID
from backend.models.message import AgentInfo, Message, MessageIntent, MessageType
from backend.models.task import TaskStatus

logger = logging.getLogger(__name__)


class Agent(ABC):
    name: str
    role: str
    capabilities: list[str]
    description: str = ""

    def __init__(self, services: AgentServices) -> None:
        self.services = services
        self.inbox: asyncio.Queue[Message] = asyncio.Queue()
        self.outbox: asyncio.Queue[Message] = asyncio.Queue()
        self.memory: dict[str, Any] = {}
        self._current_task_id: str = ""
        self._running = False
        self._task: asyncio.Task | None = None
        self._processed_ids: set[str] = set()

    @property
    def bus(self):
        return self.services.bus

    @property
    def registry(self):
        return self.services.registry

    @property
    def llm(self):
        return self.services.llm

    @property
    def shared_memory(self):
        return self.services.shared_memory

    @property
    def tools(self):
        return self.services.tools

    @property
    def task_store(self):
        return self.services.task_store

    @property
    def plugin_config(self) -> dict[str, Any]:
        return self.services.plugin_configs.get(self.name.lower(), {})

    @property
    def channel(self) -> str:
        return f"agent/{self.name}"

    async def register(self) -> None:
        info = AgentInfo(
            name=self.name,
            role=self.role,
            capabilities=self.capabilities,
            description=self.description,
            inputs=getattr(self, "inputs", []),
            outputs=getattr(self, "outputs", []),
            accepts=getattr(self, "accepts", []),
            status="idle",
        )
        await self.registry.register(info)
        await self.bus.subscribe(self.channel, self._on_message)
        if hasattr(self.bus, "replay_channel"):
            replayed = await self.bus.replay_channel(self.channel, self._on_message)  # type: ignore[union-attr]
            if replayed:
                log_event(logger, "message_replay", agent=self.name, count=replayed)
        logger.info("[%s] registered on %s", self.name, self.channel)

    async def start(self) -> None:
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        await self.registry.update_status(self.name, "running")

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        await self.bus.unsubscribe(self.channel)
        await self.registry.update_status(self.name, "stopped")

    async def send(
        self,
        to_agent: str,
        content: str,
        message_type: MessageType = MessageType.TASK,
        metadata: dict[str, Any] | None = None,
        task_id: str = "",
    ) -> Message:
        tid = task_id or self._current_task_id
        meta = dict(metadata or {})
        if tid:
            meta.setdefault("task_id", tid)
        message = Message(
            from_agent=self.name,
            to_agent=to_agent,
            content=content,
            message_type=message_type,
            metadata=meta,
            task_id=tid,
        ).with_trace()
        await self.outbox.put(message)
        await self.bus.publish(message)
        MESSAGES_SENT.labels(from_agent=self.name, to_agent=to_agent).inc()
        log_event(
            logger,
            "message_send",
            trace_id=message.trace_id,
            task_id=message.task_id,
            agent=self.name,
            to=to_agent,
            type=message_type.value,
        )
        return message

    async def receive(self) -> Message:
        return await self.inbox.get()

    async def reply_to_planner(self, message: Message, content: str) -> None:
        """Standard response back to Planner with assignment tracking."""
        await self.send(
            PLANNER,
            content,
            message_type=MessageType.RESPONSE,
            metadata={
                "intent": MessageIntent.ASSIGNMENT_RESULT.value,
                "assignment_id": message.metadata.get("assignment_id", ""),
                "attempt": message.metadata.get("attempt", 0),
                "reply_to": message.id,
            },
        )

    async def request_planner_retry(self, message: Message, content: str) -> None:
        """Ask Planner to re-run upstream work (quality loop)."""
        await self.send(
            PLANNER,
            content,
            message_type=MessageType.RESPONSE,
            metadata={
                "intent": MessageIntent.RETRY_REQUEST.value,
                "needs_retry": True,
                "assignment_id": message.metadata.get("assignment_id", ""),
                "attempt": message.metadata.get("attempt", 0),
                "reply_to": message.id,
            },
        )

    async def request_planner_approval(self, message: Message, content: str) -> None:
        """Escalate to human approval via Planner."""
        await self.send(
            PLANNER,
            content,
            message_type=MessageType.RESPONSE,
            metadata={
                "intent": MessageIntent.APPROVAL_REQUEST.value,
                "needs_approval": True,
                "assignment_id": message.metadata.get("assignment_id", ""),
                "attempt": message.metadata.get("attempt", 0),
                "reply_to": message.id,
            },
        )

    async def llm_chat(
        self,
        system_prompt: str,
        user_prompt: str,
        fallback: str,
        *,
        role: str = "default",
        stream: bool = False,
        message: Message | None = None,
    ) -> str:
        assignment_id = message.metadata.get("assignment_id", "") if message else ""

        async def on_usage(entry: LLMUsageEntry) -> None:
            if self.services.record_llm_usage and self._current_task_id:
                await self.services.record_llm_usage(
                    self._current_task_id, self.name, entry
                )

        use_stream = (
            stream
            and settings.llm_streaming
            and self.llm.available
            and self.services.stream_buffer is not None
            and self._current_task_id
        )
        if not use_stream:
            return await self.llm.chat(
                system_prompt,
                user_prompt,
                fallback,
                role=role,
                agent=self.name,
                on_usage=on_usage,
            )

        parts: list[str] = []
        async for chunk in self.llm.chat_stream(
            system_prompt,
            user_prompt,
            fallback,
            role=role,
            agent=self.name,
            on_usage=on_usage,
        ):
            parts.append(chunk)
            await self.services.stream_buffer.append(
                self._current_task_id,
                assignment_id=assignment_id,
                agent=self.name,
                chunk=chunk,
            )
        return "".join(parts) or fallback

    async def store_in_shared_memory(
        self,
        content: str,
        metadata: dict | None = None,
        task_id: str = "",
    ) -> str:
        tid = task_id or self._current_task_id
        tenant_id = DEFAULT_TENANT_ID
        if tid and self.task_store:
            task = await self.task_store.get(tid)
            if task:
                tenant_id = task.tenant_id
        return await self.shared_memory.store(
            content=content,
            agent=self.name,
            metadata=metadata,
            task_id=tid,
            tenant_id=tenant_id,
        )

    async def ask_agent(self, to_agent: str, question: str, reply_to: str = "") -> Message:
        """Ask another agent a bounded question within the current task thread."""
        from backend.core.a2a_policy import check_a2a_query, record_a2a_query

        task_id = self._current_task_id
        task = await self.task_store.get(task_id) if task_id and self.task_store else None
        ctx = dict(task.context or {}) if task else {}
        err = check_a2a_query(self.name, to_agent, ctx)
        if err:
            raise ValueError(err)
        if task and self.task_store:
            await self.task_store.save_context(task_id, record_a2a_query(ctx))
        return await self.send(
            to_agent,
            question,
            message_type=MessageType.TASK,
            metadata={
                "intent": MessageIntent.AGENT_QUERY.value,
                "reply_to": reply_to,
            },
        )

    async def _on_message(self, message: Message) -> None:
        message.with_trace()
        await self.inbox.put(message)
        log_event(
            logger,
            "message_receive",
            trace_id=message.trace_id,
            task_id=message.task_id,
            agent=self.name,
            from_agent=message.from_agent,
        )

    async def _ack_message(self, message_id: str) -> None:
        if hasattr(self.bus, "ack"):
            await self.bus.ack(message_id)  # type: ignore[union-attr]

    async def _is_duplicate(self, message: Message) -> bool:
        task_id = message.task_id or message.metadata.get("task_id", "")
        if task_id and self.task_store:
            if await self.task_store.is_message_processed(task_id, message.id):
                return True
        return message.id in self._processed_ids

    async def _mark_processed(self, message: Message) -> None:
        task_id = message.task_id or message.metadata.get("task_id", "")
        if task_id and self.task_store:
            await self.task_store.mark_message_processed(task_id, message.id)
        else:
            if len(self._processed_ids) > MAX_PROCESSED_MESSAGE_IDS:
                self._processed_ids.clear()
            self._processed_ids.add(message.id)

    async def _run_loop(self) -> None:
        while self._running:
            try:
                message = await asyncio.wait_for(self.inbox.get(), timeout=1.0)
            except asyncio.TimeoutError:
                continue

            message.with_trace()
            if await self._is_duplicate(message):
                await self._ack_message(message.id)
                continue

            await self.registry.update_status(self.name, "thinking")
            self._current_task_id = message.task_id or message.metadata.get("task_id", "")
            if self._current_task_id and self.task_store:
                task = await self.task_store.get(self._current_task_id)
                if task and task.status == TaskStatus.CANCELLED:
                    await self._ack_message(message.id)
                    continue
            try:
                from backend.core.otel import start_agent_span

                log_event(
                    logger,
                    "agent_think_start",
                    trace_id=message.trace_id,
                    task_id=self._current_task_id,
                    agent=self.name,
                    message_id=message.id,
                )
                t0 = time.monotonic()
                with start_agent_span(
                    self.name,
                    self._current_task_id,
                    message.metadata.get("assignment_id", ""),
                ):
                    response = await self.think(message)
                AGENT_THINK_SECONDS.labels(agent=self.name).observe(time.monotonic() - t0)
                if response:
                    await self.send(
                        message.from_agent,
                        response,
                        message_type=MessageType.RESPONSE,
                        metadata={
                            "intent": MessageIntent.AGENT_ANSWER.value
                            if message.metadata.get("intent") == MessageIntent.AGENT_QUERY.value
                            else MessageIntent.ASSIGNMENT_RESULT.value,
                            "reply_to": message.id,
                        },
                    )
                await self._mark_processed(message)
                await self._ack_message(message.id)
                log_event(
                    logger,
                    "agent_think_done",
                    trace_id=message.trace_id,
                    task_id=self._current_task_id,
                    agent=self.name,
                    message_id=message.id,
                )
            except Exception as exc:
                logger.exception("[%s] think() failed", self.name)
                log_event(
                    logger,
                    "agent_think_failed",
                    trace_id=message.trace_id,
                    task_id=self._current_task_id,
                    agent=self.name,
                    error=str(exc),
                )
                assignment_id = message.metadata.get("assignment_id", "")
                is_worker_assignment = (
                    message.from_agent == PLANNER and bool(assignment_id)
                )
                await self.send(
                    message.from_agent,
                    f"Error: {exc}",
                    message_type=MessageType.ERROR,
                    metadata={
                        "intent": MessageIntent.ASSIGNMENT_ERROR.value,
                        "assignment_id": assignment_id,
                        "attempt": message.metadata.get("attempt", 0),
                        "reply_to": message.id,
                    },
                )
                if is_worker_assignment:
                    await self._ack_message(message.id)
                    continue
                if self._current_task_id and self.task_store:
                    await self.task_store.mark_failed(self._current_task_id, str(exc))
                    if self.services.on_task_finished:
                        await self.services.on_task_finished(self._current_task_id)
            finally:
                await self.registry.update_status(self.name, "idle")

    @abstractmethod
    async def think(self, message: Message) -> str | None:
        """Process an incoming message and optionally return a reply."""

    def remember(self, key: str, value: Any) -> None:
        self.memory[key] = value

    def recall(self, key: str, default: Any = None) -> Any:
        return self.memory.get(key, default)

    async def recall_shared(self, query: str, limit: int = 3) -> str:
        tenant_id = DEFAULT_TENANT_ID
        if self._current_task_id and self.task_store:
            task = await self.task_store.get(self._current_task_id)
            if task:
                tenant_id = task.tenant_id
        entries = await self.shared_memory.query(
            query,
            limit=limit,
            task_id=self._current_task_id,
            tenant_id=tenant_id,
        )
        if not entries:
            return ""
        return "\n\n".join(f"[{e.agent}] {e.content}" for e in entries)
