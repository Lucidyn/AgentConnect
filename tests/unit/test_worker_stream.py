"""Unit tests for worker stream hub."""

from __future__ import annotations

import pytest

from backend.config import settings
from backend.core.worker_protocol import WorkerResultEnvelope, WorkerTaskEnvelope
from backend.core.worker_stream import InMemoryWorkerStream, RedisWorkerStream, reset_worker_stream_for_tests


@pytest.fixture(autouse=True)
def _reset_hub():
    reset_worker_stream_for_tests()
    yield
    reset_worker_stream_for_tests()


@pytest.mark.asyncio
async def test_in_memory_task_roundtrip():
    hub = InMemoryWorkerStream()
    await hub.connect()
    envelope = WorkerTaskEnvelope(
        envelope_id="e1",
        task_id="task-1",
        assignment_id="t1",
        agent="Coder",
        payload="implement api",
    )
    await hub.publish_task(envelope)
    items = await hub.consume_tasks(consumer="c1", agent="Coder", block_ms=500)
    assert len(items) == 1
    assert items[0][1].payload == "implement api"


@pytest.mark.asyncio
async def test_in_memory_result_roundtrip():
    hub = InMemoryWorkerStream()
    await hub.connect()
    result = WorkerResultEnvelope(
        envelope_id="e1",
        task_id="task-1",
        assignment_id="t1",
        agent="Coder",
        success=True,
        content="done",
    )
    await hub.publish_result(result)
    items = await hub.consume_results(consumer="planner", block_ms=500)
    assert len(items) == 1
    assert items[0][1].content == "done"


@pytest.mark.asyncio
async def test_consumer_filters_by_agent():
    hub = InMemoryWorkerStream()
    await hub.connect()
    await hub.publish_task(
        WorkerTaskEnvelope(
            envelope_id="e1",
            task_id="t",
            assignment_id="a1",
            agent="Research",
            payload="r",
        )
    )
    await hub.publish_task(
        WorkerTaskEnvelope(
            envelope_id="e2",
            task_id="t",
            assignment_id="a2",
            agent="Coder",
            payload="c",
        )
    )
    coder_items = await hub.consume_tasks(consumer="w1", agent="Coder", block_ms=500)
    assert len(coder_items) == 1
    assert coder_items[0][1].agent == "Coder"


@pytest.mark.asyncio
async def test_redis_requeues_wrong_agent_tasks():
    calls: list[tuple[str, tuple]] = []

    class FakeRedis:
        async def xreadgroup(self, group, consumer, streams, count=1, block=0):
            del group, consumer, block
            if not hasattr(self, "_read_once"):
                self._read_once = True
                payload = WorkerTaskEnvelope(
                    envelope_id="e1",
                    task_id="t1",
                    assignment_id="a1",
                    agent="Writer",
                    payload="write",
                    attempt=1,
                    trace_id="t1",
                    metadata={},
                ).model_dump_json()
                return [(settings.worker_stream_key, [("1-0", {"data": payload})])]
            return []

        async def xack(self, stream, group, stream_id):
            calls.append(("xack", (stream, group, stream_id)))

        async def xadd(self, stream, fields):
            calls.append(("xadd", (stream, fields)))
            return "2-0"

    hub = RedisWorkerStream(redis_url="redis://fake/0")
    hub._redis = FakeRedis()
    hub._group = "workers"

    items = await hub.consume_tasks(consumer="research-1", agent="Research", count=1, block_ms=10)
    assert items == []
    assert ("xack", (settings.worker_stream_key, "workers", "1-0")) in calls
    assert any(call[0] == "xadd" for call in calls)
