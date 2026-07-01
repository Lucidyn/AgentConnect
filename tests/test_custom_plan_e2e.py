"""End-to-end test for custom DAG plan submission."""

from __future__ import annotations

import asyncio

import pytest

from backend.models.task import TaskStatus
from backend.platform import Platform
from backend.tools.base import ToolResult
from backend.tools.registry import ToolRegistry


async def _mock_run_for_task(self, task: str) -> list[ToolResult]:
    return [ToolResult("mock", True, "mock research")]


@pytest.mark.asyncio
async def test_custom_plan_parallel_fork_completes(isolated_paths, monkeypatch):
    monkeypatch.setattr("backend.config.settings.max_concurrent_tasks", 1)
    monkeypatch.setattr("backend.config.settings.fast_skip_planner_llm", True)
    monkeypatch.setattr("backend.config.settings.fast_mode", True)
    monkeypatch.setattr("backend.config.settings.fast_skip_test_runner", True)
    monkeypatch.setattr(ToolRegistry, "run_for_task", _mock_run_for_task)

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
            collaboration_mode="blackboard",
            negotiation=True,
        )
        assert message is not None

        final = None
        for _ in range(150):
            final = await platform.task_store.get(task.id)
            if final and final.status in (
                TaskStatus.COMPLETED,
                TaskStatus.FAILED,
                TaskStatus.WAITING_APPROVAL,
            ):
                break
            await asyncio.sleep(0.1)

        assert final is not None
        assert final.status == TaskStatus.COMPLETED, (
            f"expected completed, got {final.status}, error={final.error}"
        )
        assert final.plan is not None
        statuses = {a["id"]: a["status"] for a in final.plan["assignments"]}
        assert statuses.get("t3") == "done"
        ctx = final.context or {}
        assert ctx.get("collaboration_mode") == "blackboard"
        assert ctx.get("negotiation") is True
    finally:
        await platform.stop()
