"""Redis Stream / in-memory queue for distributed worker assignments."""

from __future__ import annotations

import asyncio
import json
import logging
import socket
from abc import ABC, abstractmethod
from typing import Any
from uuid import uuid4

from backend.config import settings
from backend.core.worker_protocol import WorkerResultEnvelope, WorkerTaskEnvelope

logger = logging.getLogger(__name__)

_shared_memory_hub: InMemoryWorkerStream | None = None


def reset_worker_stream_for_tests() -> None:
    """Clear in-memory hub between tests."""
    global _shared_memory_hub
    _shared_memory_hub = None


def default_consumer_name() -> str:
    custom = (settings.worker_consumer_name or "").strip()
    if custom:
        return custom
    return f"{socket.gethostname()}-{uuid4().hex[:8]}"


def parse_remote_agents(enabled_names: list[str] | None = None) -> set[str]:
    """Agents executed in worker processes when distributed mode is on."""
    raw = (settings.worker_agents or "").strip()
    if raw:
        return {name.strip() for name in raw.split(",") if name.strip()}
    if enabled_names:
        return {name for name in enabled_names if name != "Planner"}
    return {
        "Research",
        "Coder",
        "Writer",
        "Analyst",
        "Translator",
        "Reviewer",
        "TestRunner",
        "Vision",
    }


class WorkerStreamHub(ABC):
    @abstractmethod
    async def connect(self) -> None: ...

    @abstractmethod
    async def disconnect(self) -> None: ...

    @abstractmethod
    async def publish_task(self, envelope: WorkerTaskEnvelope) -> str: ...

    @abstractmethod
    async def publish_result(self, envelope: WorkerResultEnvelope) -> str: ...

    @abstractmethod
    async def consume_tasks(
        self,
        *,
        consumer: str,
        agent: str,
        count: int = 1,
        block_ms: int = 2000,
    ) -> list[tuple[str, WorkerTaskEnvelope]]: ...

    @abstractmethod
    async def ack_task(self, stream_id: str, consumer: str) -> None: ...

    @abstractmethod
    async def consume_results(
        self,
        *,
        consumer: str,
        count: int = 10,
        block_ms: int = 1000,
    ) -> list[tuple[str, WorkerResultEnvelope]]: ...

    @abstractmethod
    async def ack_result(self, stream_id: str, consumer: str) -> None: ...


class InMemoryWorkerStream(WorkerStreamHub):
    """Test/local fallback — asyncio queues with stream ids."""

    def __init__(self) -> None:
        self._task_queue: asyncio.Queue[tuple[str, WorkerTaskEnvelope]] = asyncio.Queue()
        self._result_queue: asyncio.Queue[tuple[str, WorkerResultEnvelope]] = asyncio.Queue()
        self._task_seq = 0
        self._result_seq = 0

    async def connect(self) -> None:
        logger.info("In-memory worker stream ready")

    async def disconnect(self) -> None:
        return None

    async def publish_task(self, envelope: WorkerTaskEnvelope) -> str:
        self._task_seq += 1
        stream_id = f"task-{self._task_seq}"
        await self._task_queue.put((stream_id, envelope))
        return stream_id

    async def publish_result(self, envelope: WorkerResultEnvelope) -> str:
        self._result_seq += 1
        stream_id = f"result-{self._result_seq}"
        await self._result_queue.put((stream_id, envelope))
        return stream_id

    async def consume_tasks(
        self,
        *,
        consumer: str,
        agent: str,
        count: int = 1,
        block_ms: int = 2000,
    ) -> list[tuple[str, WorkerTaskEnvelope]]:
        del consumer
        items: list[tuple[str, WorkerTaskEnvelope]] = []
        deadline = asyncio.get_event_loop().time() + block_ms / 1000
        while len(items) < count:
            timeout = max(0.01, deadline - asyncio.get_event_loop().time())
            try:
                stream_id, envelope = await asyncio.wait_for(
                    self._task_queue.get(), timeout=timeout
                )
            except asyncio.TimeoutError:
                break
            if envelope.agent == agent:
                items.append((stream_id, envelope))
            else:
                await self._task_queue.put((stream_id, envelope))
                await asyncio.sleep(0.01)
        return items

    async def ack_task(self, stream_id: str, consumer: str) -> None:
        del stream_id, consumer

    async def consume_results(
        self,
        *,
        consumer: str,
        count: int = 10,
        block_ms: int = 1000,
    ) -> list[tuple[str, WorkerResultEnvelope]]:
        del consumer
        items: list[tuple[str, WorkerResultEnvelope]] = []
        deadline = asyncio.get_event_loop().time() + block_ms / 1000
        while len(items) < count:
            timeout = max(0.01, deadline - asyncio.get_event_loop().time())
            try:
                items.append(
                    await asyncio.wait_for(self._result_queue.get(), timeout=timeout)
                )
            except asyncio.TimeoutError:
                break
        return items

    async def ack_result(self, stream_id: str, consumer: str) -> None:
        del stream_id, consumer


class RedisWorkerStream(WorkerStreamHub):
    def __init__(self, redis_url: str | None = None) -> None:
        self._url = redis_url or settings.redis_url
        self._redis: Any = None
        self._group = settings.worker_consumer_group

    async def connect(self) -> None:
        from redis.asyncio import Redis
        from redis.exceptions import ResponseError

        self._redis = Redis.from_url(self._url, decode_responses=True)
        for stream in (settings.worker_stream_key, settings.worker_result_stream_key):
            try:
                await self._redis.xgroup_create(stream, self._group, id="0", mkstream=True)
            except ResponseError as exc:
                if "BUSYGROUP" not in str(exc):
                    raise
        logger.info("Redis worker streams ready (%s)", self._url)

    async def disconnect(self) -> None:
        if self._redis:
            await self._redis.aclose()
            self._redis = None

    async def publish_task(self, envelope: WorkerTaskEnvelope) -> str:
        assert self._redis is not None
        payload = envelope.model_dump_json()
        return await self._redis.xadd(settings.worker_stream_key, {"data": payload})

    async def publish_result(self, envelope: WorkerResultEnvelope) -> str:
        assert self._redis is not None
        payload = envelope.model_dump_json()
        return await self._redis.xadd(settings.worker_result_stream_key, {"data": payload})

    async def consume_tasks(
        self,
        *,
        consumer: str,
        agent: str,
        count: int = 1,
        block_ms: int = 2000,
    ) -> list[tuple[str, WorkerTaskEnvelope]]:
        assert self._redis is not None
        rows = await self._redis.xreadgroup(
            self._group,
            consumer,
            {settings.worker_stream_key: ">"},
            count=count * 3,
            block=block_ms,
        )
        items: list[tuple[str, WorkerTaskEnvelope]] = []
        for _stream, messages in rows or []:
            for stream_id, fields in messages:
                envelope = WorkerTaskEnvelope.model_validate_json(fields["data"])
                if envelope.agent == agent:
                    items.append((stream_id, envelope))
                if len(items) >= count:
                    break
        return items

    async def ack_task(self, stream_id: str, consumer: str) -> None:
        del consumer
        assert self._redis is not None
        await self._redis.xack(settings.worker_stream_key, self._group, stream_id)

    async def consume_results(
        self,
        *,
        consumer: str,
        count: int = 10,
        block_ms: int = 1000,
    ) -> list[tuple[str, WorkerResultEnvelope]]:
        assert self._redis is not None
        rows = await self._redis.xreadgroup(
            self._group,
            consumer,
            {settings.worker_result_stream_key: ">"},
            count=count,
            block=block_ms,
        )
        items: list[tuple[str, WorkerResultEnvelope]] = []
        for _stream, messages in rows or []:
            for stream_id, fields in messages:
                items.append(
                    (
                        stream_id,
                        WorkerResultEnvelope.model_validate_json(fields["data"]),
                    )
                )
        return items

    async def ack_result(self, stream_id: str, consumer: str) -> None:
        del consumer
        assert self._redis is not None
        await self._redis.xack(settings.worker_result_stream_key, self._group, stream_id)


async def create_worker_stream() -> WorkerStreamHub:
    global _shared_memory_hub
    if settings.use_redis:
        hub: WorkerStreamHub = RedisWorkerStream()
        await hub.connect()
        return hub
    if _shared_memory_hub is None:
        _shared_memory_hub = InMemoryWorkerStream()
        await _shared_memory_hub.connect()
    return _shared_memory_hub


def envelope_from_assignment(
    *,
    task_id: str,
    assignment_id: str,
    agent: str,
    payload: str,
    attempt: int,
    metadata: dict,
) -> WorkerTaskEnvelope:
    return WorkerTaskEnvelope(
        envelope_id=str(uuid4()),
        task_id=task_id,
        assignment_id=assignment_id,
        agent=agent,
        payload=payload,
        attempt=attempt,
        trace_id=task_id,
        metadata=metadata,
    )
