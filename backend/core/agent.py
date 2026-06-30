"""Base Agent — inbox, outbox, memory, send/receive/think lifecycle."""

from __future__ import annotations

import asyncio
import logging
import time
from abc import ABC, abstractmethod
from typing import Any

from backend.constants import MAX_PROCESSED_MESSAGE_IDS, PLANNER
from backend.core.metrics import AGENT_THINK_SECONDS, MESSAGES_SENT
from backend.core.services import AgentServices
from backend.core.trace import log_event
from backend.models.message import AgentInfo, Message, MessageType
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
            metadata={"assignment_id": message.metadata.get("assignment_id", "")},
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
            await self._mark_processed(message)

            await self.registry.update_status(self.name, "thinking")
            self._current_task_id = message.task_id or message.metadata.get("task_id", "")
            if self._current_task_id and self.task_store:
                task = await self.task_store.get(self._current_task_id)
                if task and task.status == TaskStatus.CANCELLED:
                    await self._ack_message(message.id)
                    continue
            try:
                log_event(
                    logger,
                    "agent_think_start",
                    trace_id=message.trace_id,
                    task_id=self._current_task_id,
                    agent=self.name,
                    message_id=message.id,
                )
                t0 = time.monotonic()
                response = await self.think(message)
                AGENT_THINK_SECONDS.labels(agent=self.name).observe(time.monotonic() - t0)
                if response:
                    await self.send(
                        message.from_agent,
                        response,
                        message_type=MessageType.RESPONSE,
                        metadata={"reply_to": message.id},
                    )
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
                await self.send(
                    message.from_agent,
                    f"Error: {exc}",
                    message_type=MessageType.ERROR,
                )
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
        entries = await self.shared_memory.query(
            query, limit=limit, task_id=self._current_task_id
        )
        if not entries:
            return ""
        return "\n\n".join(f"[{e.agent}] {e.content}" for e in entries)
