"""LLM usage tracking tests."""

import pytest

from backend.core.llm_usage import LLMUsageEntry, estimate_cost, merge_usage
from backend.models.task_context import TaskContext


def test_merge_usage_totals():
    entries = [
        LLMUsageEntry(agent="Coder", prompt_tokens=100, completion_tokens=50, total_tokens=150),
        LLMUsageEntry(agent="Writer", prompt_tokens=200, completion_tokens=80, total_tokens=280),
    ]
    totals = merge_usage(entries)
    assert totals["prompt_tokens"] == 300
    assert totals["completion_tokens"] == 130
    assert totals["total_tokens"] == 430
    assert totals["calls"] == 2


def test_estimate_cost():
    cost = estimate_cost(
        {"prompt_tokens": 1000, "completion_tokens": 500},
        input_per_1k=0.001,
        output_per_1k=0.002,
    )
    assert cost == pytest.approx(0.002)


@pytest.mark.asyncio
async def test_task_context_stores_llm_usage(db_path):
    from backend.core.task_store import TaskStore

    store = TaskStore(db_path)
    await store.connect()
    task = await store.create("usage test")
    ctx = TaskContext(
        llm_usage=[
            LLMUsageEntry(agent="Planner", prompt_tokens=10, completion_tokens=5, total_tokens=15)
        ]
    )
    await store.save_context(task.id, ctx.model_dump(mode="json"))
    loaded = await store.get(task.id)
    saved = TaskContext.model_validate(loaded.context or {})
    assert len(saved.llm_usage) == 1
    assert saved.llm_usage[0].agent == "Planner"
    await store.disconnect()
