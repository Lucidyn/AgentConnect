"""Redis message bus integration tests (skipped when Redis is unavailable)."""

import asyncio
import os

import pytest
import pytest_asyncio

from backend.core.message_bus import RedisMessageBus
from backend.models.message import Message, MessageType

REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")

pytestmark = pytest.mark.redis


def redis_reachable() -> bool:
    try:
        import redis

        client = redis.from_url(REDIS_URL, socket_connect_timeout=1)
        client.ping()
        client.close()
        return True
    except Exception:
        return False


@pytest_asyncio.fixture
async def redis_bus():
    if not redis_reachable():
        pytest.skip("Redis not available")
    bus = RedisMessageBus(REDIS_URL)
    await bus.connect()
    yield bus
    await bus.disconnect()


@pytest.mark.asyncio
async def test_redis_publish_subscribe(redis_bus):
    received: list[Message] = []

    async def handler(msg: Message) -> None:
        received.append(msg)

    await redis_bus.subscribe("agent/TestRedis", handler)

    msg = Message(
        from_agent="User",
        to_agent="TestRedis",
        content="ping",
        message_type=MessageType.TASK,
        task_id="redis-test-1",
    ).with_trace()
    await redis_bus.publish(msg)

    for _ in range(20):
        await asyncio.sleep(0.05)
        if received:
            break

    assert len(received) == 1
    assert received[0].content == "ping"
    assert received[0].task_id == "redis-test-1"


@pytest.mark.asyncio
async def test_create_message_bus_uses_redis_when_available(monkeypatch):
    if not redis_reachable():
        pytest.skip("Redis not available")

    from backend.config import settings
    from backend.core.message_bus import RedisMessageBus, create_message_bus

    monkeypatch.setattr(settings, "use_redis", True)
    monkeypatch.setattr(settings, "redis_url", REDIS_URL)
    monkeypatch.setattr(settings, "message_reliability", False)

    bus = await create_message_bus()
    try:
        assert isinstance(bus, RedisMessageBus)
    finally:
        await bus.disconnect()
