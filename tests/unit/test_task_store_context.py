import asyncio

import pytest

from backend.core.llm_usage import LLMUsageEntry
from backend.core.task_store import TaskStore
from backend.models.task_context import TaskContext


@pytest.fixture
async def store(isolated_paths):
    s = TaskStore(isolated_paths["tasks"])
    await s.connect()
    yield s
    await s.disconnect()


@pytest.mark.asyncio
async def test_append_llm_usage_concurrent(store):
    task = await store.create("hello", tenant_id="default")
    entries = [
        LLMUsageEntry(agent="Research", model="gpt-4o-mini", prompt_tokens=10, completion_tokens=5, total_tokens=15),
        LLMUsageEntry(agent="Coder", model="gpt-4o-mini", prompt_tokens=20, completion_tokens=8, total_tokens=28),
    ]

    await asyncio.gather(
        store.append_llm_usage(task.id, entries[0]),
        store.append_llm_usage(task.id, entries[1]),
    )

    loaded = await store.get(task.id)
    ctx = TaskContext.model_validate(loaded.context or {})
    assert len(ctx.llm_usage) == 2
    assert {e.agent for e in ctx.llm_usage} == {"Research", "Coder"}


@pytest.mark.asyncio
async def test_mutate_context_preserves_llm_usage(store):
    task = await store.create("hello", tenant_id="default")
    await store.append_llm_usage(
        task.id,
        LLMUsageEntry(agent="Planner", model="gpt-4o-mini", prompt_tokens=1, completion_tokens=1, total_tokens=2),
    )

    def _mark(ctx: TaskContext) -> None:
        ctx.a2a_query_count += 1

    await store.mutate_context(task.id, _mark)

    loaded = await store.get(task.id)
    ctx = TaskContext.model_validate(loaded.context or {})
    assert ctx.a2a_query_count == 1
    assert len(ctx.llm_usage) == 1
