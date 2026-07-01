"""Integration test for distributed worker pipeline (in-memory stream)."""

from __future__ import annotations

import asyncio

import pytest

from backend.core.worker_stream import reset_worker_stream_for_tests
from backend.models.task import TaskStatus
from backend.platform import Platform
from backend.tools.base import ToolResult
from backend.tools.registry import ToolRegistry
from backend.worker.platform import WorkerPlatform


async def _mock_run_for_task(self, task: str) -> list[ToolResult]:
    return [ToolResult("mock", True, "mock research")]


@pytest.mark.asyncio
async def test_distributed_workers_complete_task(isolated_paths, monkeypatch):
    monkeypatch.setattr("backend.config.settings.distributed_workers", True)
    monkeypatch.setattr("backend.config.settings.use_redis", False)
    monkeypatch.setattr(
        "backend.config.settings.worker_agents",
        "Research,Coder,Reviewer,TestRunner",
    )
    monkeypatch.setattr("backend.config.settings.max_concurrent_tasks", 1)
    monkeypatch.setattr("backend.config.settings.fast_mode", True)
    monkeypatch.setattr("backend.config.settings.fast_skip_planner_llm", True)
    monkeypatch.setattr("backend.config.settings.fast_skip_test_runner", True)
    monkeypatch.setattr(ToolRegistry, "run_for_task", _mock_run_for_task)

    reset_worker_stream_for_tests()

    worker_platforms: list[WorkerPlatform] = []
    worker_tasks: list[asyncio.Task] = []
    for name in ("Research", "Coder", "Reviewer"):
        wp = WorkerPlatform(name)
        await wp.start()
        worker_platforms.append(wp)
        worker_tasks.append(asyncio.create_task(wp.run_loop()))

    api = Platform()
    await api.start()
    try:
        task, message = await api.submit_task("distributed health api")
        assert message is not None

        final = None
        for _ in range(200):
            final = await api.task_store.get(task.id)
            if final and final.status == TaskStatus.COMPLETED:
                break
            await asyncio.sleep(0.05)

        assert final is not None, "task did not complete"
        assert final.status == TaskStatus.COMPLETED
        assert final.plan is not None
    finally:
        for wp in worker_platforms:
            wp._running = False
        for t in worker_tasks:
            t.cancel()
            try:
                await t
            except asyncio.CancelledError:
                pass
        for wp in worker_platforms:
            await wp.stop()
        await api.stop()
        reset_worker_stream_for_tests()
