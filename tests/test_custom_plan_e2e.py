"""End-to-end test for custom DAG plan submission."""

from __future__ import annotations

import pytest
import asyncio
import time

from backend.models.task import TaskStatus
from backend.platform import Platform

@pytest.mark.asyncio
async def test_custom_plan_parallel_fork_completes(isolated_paths, mock_tools, monkeypatch):
    monkeypatch.setattr("backend.config.settings.max_concurrent_tasks", 1)
    monkeypatch.setattr("backend.config.settings.fast_skip_planner_llm", True)
    monkeypatch.setattr("backend.config.settings.fast_mode", True)
    monkeypatch.setattr("backend.config.settings.fast_skip_test_runner", True)

    custom_plan = {
        "summary": "并行测试：{task}",
        "assignments": [
            {"id": "t1", "agent": "Research", "task": "调研：{task}", "depends_on": []},
            {"id": "t2", "agent": "Coder", "task": "实现：{task}", "depends_on": []},
            {
                "id": "t3",
                "agent": "Reviewer",
                "task": "审查：{task}",
                "depends_on": ["t1", "t2"],
            },
        ],
    }

    platform = Platform()
    await platform.start()
    try:
        task, message = await platform.submit_task(
            "custom parallel api",
            custom_plan=custom_plan,
        )
        assert message is not None

        deadline = 60.0
        final = None
        end = time.monotonic() + deadline
        while time.monotonic() < end:
            current = await platform.task_store.get(task.id)
            if not current:
                await asyncio.sleep(0.05)
                continue
            if current.status == TaskStatus.COMPLETED:
                final = current
                break
            if current.status == TaskStatus.WAITING_APPROVAL:
                await platform.approve_task(task.id, "approve")
            await asyncio.sleep(0.05)

        if final is None:
            final = await platform.task_store.get(task.id)

        assert final is not None
        assert final.status == TaskStatus.COMPLETED, (
            f"expected completed, got {final.status}, error={final.error}"
        )
        assert final.plan is not None
        statuses = {a["id"]: a["status"] for a in final.plan["assignments"]}
        assert statuses.get("t3") == "done"
        ctx = final.context or {}
        assert ctx.get("collaboration_mode") == "planner"
        assert ctx.get("negotiation") is False
    finally:
        await platform.stop()
