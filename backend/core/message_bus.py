"""Message Bus — decoupled agent communication via Redis Pub/Sub or in-memory fallback."""

from __future__ import annotations

import asyncio
import json
import logging
from abc import ABC, abstractmethod
from collections import defaultdict
from typing import TYPE_CHECKING, Awaitable, Callable

from backend.config import settings
from backend.models.message import Message

if TYPE_CHECKING:
    from backend.core.message_outbox import MessageOutbox

logger = logging.getLogger(__name__)

MessageHandler = Callable[[Message], Awaitable[None]]


class MessageBus(ABC):
    @abstractmethod
    async def connect(self) -> None: ...

    @abstractmethod
    async def disconnect(self) -> None: ...

    @abstractmethod
    async def publish(self, message: Message, *, track: bool = True) -> None: ...

    @abstractmethod
    async def subscribe(self, channel: str, handler: MessageHandler) -> None: ...

    @abstractmethod
    async def unsubscribe(self, channel: str) -> None: ...


class InMemoryMessageBus(MessageBus):
    """Fallback bus for local dev without Redis."""

    def __init__(self) -> None:
        self._handlers: dict[str, list[MessageHandler]] = defaultdict(list)
        self._history: list[Message] = []
        self._listeners: list[Callable[[Message], Awaitable[None]]] = []

    async def connect(self) -> None:
        logger.info("In-memory message bus ready")

    async def disconnect(self) -> None:
        self._handlers.clear()

    def add_global_listener(self, listener: Callable[[Message], Awaitable[None]]) -> None:
        self._listeners.append(listener)

    @property
    def history(self) -> list[Message]:
        return list(self._history)

    async def publish(self, message: Message, *, track: bool = True) -> None:
        message.with_trace()
        self._history.append(message)
        for listener in self._listeners:
            await listener(message)

        channel = message.channel_for_recipient()
        handlers = self._handlers.get(channel, [])
        for handler in handlers:
            asyncio.create_task(handler(message))

        if message.message_type.value == "broadcast":
            for ch, ch_handlers in self._handlers.items():
                if ch != channel:
                    for handler in ch_handlers:
                        asyncio.create_task(handler(message))

    async def subscribe(self, channel: str, handler: MessageHandler) -> None:
        self._handlers[channel].append(handler)
        logger.debug("Subscribed to %s", channel)

    async def unsubscribe(self, channel: str) -> None:
        self._handlers.pop(channel, None)


class RedisMessageBus(MessageBus):
    def __init__(self, redis_url: str) -> None:
        self._redis_url = redis_url
        self._redis = None
        self._pubsub = None
        self._handlers: dict[str, list[MessageHandler]] = defaultdict(list)
        self._listener_task: asyncio.Task | None = None
        self._global_listeners: list[Callable[[Message], Awaitable[None]]] = []

    def add_global_listener(self, listener: Callable[[Message], Awaitable[None]]) -> None:
        self._global_listeners.append(listener)

    async def connect(self) -> None:
        import redis.asyncio as aioredis

        self._redis = aioredis.from_url(self._redis_url, decode_responses=True)
        self._pubsub = self._redis.pubsub()
        self._listener_task = asyncio.create_task(self._listen_loop())
        logger.info("Redis message bus connected: %s", self._redis_url)

    async def disconnect(self) -> None:
        if self._listener_task:
            self._listener_task.cancel()
            try:
                await self._listener_task
            except asyncio.CancelledError:
                pass
        if self._pubsub:
            await self._pubsub.close()
        if self._redis:
            await self._redis.close()

    async def publish(self, message: Message, *, track: bool = True) -> None:
        if not self._redis:
            raise RuntimeError("Message bus not connected")

        message.with_trace()
        channel = message.channel_for_recipient()
        payload = message.to_json()
        await self._redis.publish(channel, payload)

        for listener in self._global_listeners:
            await listener(message)

        if message.message_type.value == "broadcast":
            await self._redis.publish("agent/broadcast", payload)

    async def subscribe(self, channel: str, handler: MessageHandler) -> None:
        if not self._pubsub:
            raise RuntimeError("Message bus not connected")

        self._handlers[channel].append(handler)
        await self._pubsub.subscribe(channel)
        logger.debug("Subscribed to %s", channel)

    async def unsubscribe(self, channel: str) -> None:
        if self._pubsub:
            await self._pubsub.unsubscribe(channel)
        self._handlers.pop(channel, None)

    async def _listen_loop(self) -> None:
        assert self._pubsub is not None
        async for raw in self._pubsub.listen():
            if raw["type"] != "message":
                continue
            try:
                message = Message.from_json(raw["data"])
            except (json.JSONDecodeError, ValueError):
                logger.warning("Invalid message payload on %s", raw.get("channel"))
                continue

            channel = raw["channel"]
            handlers = self._handlers.get(channel, [])
            for handler in handlers:
                asyncio.create_task(handler(message))


async def create_message_bus(outbox: "MessageOutbox | None" = None) -> MessageBus:
    inner: MessageBus
    if settings.use_redis:
        try:
            bus = RedisMessageBus(settings.redis_url)
            await bus.connect()
            await bus._redis.ping()  # type: ignore[union-attr]
            inner = bus
        except Exception as exc:
            logger.warning("Redis unavailable (%s), falling back to in-memory bus", exc)
            inner = InMemoryMessageBus()
            await inner.connect()
    else:
        inner = InMemoryMessageBus()
        await inner.connect()

    if settings.message_reliability and outbox is not None:
        return ReliableMessageBus(inner, outbox)
    return inner


class ReliableMessageBus(MessageBus):
    """Wraps a bus with SQLite outbox for ACK tracking and retry."""

    def __init__(self, inner: MessageBus, outbox: MessageOutbox) -> None:
        self._inner = inner
        self.outbox = outbox

    async def connect(self) -> None:
        await self._inner.connect()

    async def disconnect(self) -> None:
        await self._inner.disconnect()
        await self.outbox.disconnect()

    def add_global_listener(self, listener: Callable[[Message], Awaitable[None]]) -> None:
        if hasattr(self._inner, "add_global_listener"):
            self._inner.add_global_listener(listener)  # type: ignore[union-attr]

    @property
    def history(self) -> list[Message]:
        if isinstance(self._inner, InMemoryMessageBus):
            return self._inner.history
        return []

    async def publish(self, message: Message, *, track: bool = True) -> None:
        message.with_trace()
        channel = message.channel_for_recipient()
        if track:
            await self.outbox.enqueue(message, channel)
        await self._inner.publish(message, track=False)

    async def subscribe(self, channel: str, handler: MessageHandler) -> None:
        await self._inner.subscribe(channel, handler)

    async def unsubscribe(self, channel: str) -> None:
        await self._inner.unsubscribe(channel)

    async def ack(self, message_id: str) -> None:
        await self.outbox.ack(message_id)

    async def replay_channel(self, channel: str, handler: MessageHandler) -> int:
        pending = await self.outbox.pending_for_channel(channel)
        for message in pending:
            await handler(message)
        return len(pending)

