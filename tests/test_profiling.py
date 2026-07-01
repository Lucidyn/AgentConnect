"""Smoke tests for pipeline profiling utilities."""

import pytest

from backend.core.profiling import PipelineProfiler
from backend.models.task import TaskStatus
from backend.platform import Platform
from backend.tools.base import ToolResult
from backend.tools.registry import ToolRegistry


async def _mock_run_for_task(self, task: str) -> list[ToolResult]:
    return [ToolResult("mock", True, f"mock research for {task[:40]}")]


@pytest.mark.asyncio
async def test_pipeline_profiler_collects_events(isolated_paths, monkeypatch):
    monkeypatch.setattr("backend.config.settings.max_concurrent_tasks", 1)
    monkeypatch.setattr(ToolRegistry, "run_for_task", _mock_run_for_task)

    profiler = PipelineProfiler()
    platform = Platform()
    profiler.attach_platform(platform)
    profiler.wrap_agents(platform.agents)

    await platform.start()
    try:
        profiler.mark("test.start")
        task, _ = await platform.submit_task("build a tiny health API")
        status = await profiler.watch_task(platform.task_store, task.id, timeout=15)
        profiler.mark("test.end")
    finally:
        profiler.detach()
        await platform.stop()

    summary = profiler.summary()
    assert status == TaskStatus.COMPLETED
    assert summary["total_ms"] > 0
    assert summary["messages"] > 0
    assert summary["llm_calls"] >= 1
    assert any(e["name"].startswith("assignment.") for e in summary["events"])
    assert "task.finished.completed" in {e["name"] for e in summary["events"]}

    report = profiler.report_text()
    assert "Pipeline Profile" in report
    assert "Agent think()" in report
