"""End-to-end pipeline test with mocked external tools."""

import asyncio

import pytest

from backend.models.task import TaskStatus
from backend.platform import Platform
from backend.tools.base import ToolResult
from backend.tools.registry import ToolRegistry


async def _mock_run_for_task(self, task: str) -> list[ToolResult]:
    return [ToolResult("mock", True, f"mock research for {task[:40]}")]


@pytest.mark.asyncio
async def test_full_pipeline_completes(isolated_paths, monkeypatch):
    monkeypatch.setattr("backend.config.settings.max_concurrent_tasks", 1)
    monkeypatch.setattr(ToolRegistry, "run_for_task", _mock_run_for_task)

    platform = Platform()
    await platform.start()
    try:
        task, message = await platform.submit_task("build a tiny health API")
        assert message is not None

        final = None
        for _ in range(40):
            final = await platform.task_store.get(task.id)
            if final and final.status == TaskStatus.COMPLETED:
                break
            await asyncio.sleep(0.1)

        assert final is not None
        assert final.status == TaskStatus.COMPLETED
        assert final.plan is not None
        statuses = {a["id"]: a["status"] for a in final.plan["assignments"]}
        assert statuses.get("t1") == "done"
        assert statuses.get("t2") == "done"
        assert statuses.get("t3") == "done"
        assert final.result
    finally:
        await platform.stop()
