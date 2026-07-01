"""End-to-end test for custom DAG plan submission."""

from __future__ import annotations

import pytest

from backend.models.task import TaskStatus
from backend.platform import Platform
from tests.helpers import wait_for_task_status


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
            collaboration_mode="blackboard",
            negotiation=True,
        )
        assert message is not None

        final = await wait_for_task_status(
            platform.task_store, task.id, TaskStatus.COMPLETED, timeout=15.0
        )

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
