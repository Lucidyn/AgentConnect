"""Unit tests for worker stream hub."""

from __future__ import annotations

import pytest

from backend.core.worker_protocol import WorkerResultEnvelope, WorkerTaskEnvelope
from backend.core.worker_stream import InMemoryWorkerStream, reset_worker_stream_for_tests


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
