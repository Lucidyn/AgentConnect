"""Shared test utilities."""

from __future__ import annotations

import asyncio
import time

from backend.models.task import TaskStatus
from backend.tools.base import ToolResult


async def wait_for_task_status(
    store,
    task_id: str,
    status: TaskStatus,
    *,
    timeout: float = 8.0,
    interval: float = 0.05,
):
    """Poll task store until task reaches status or timeout."""
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        last = await store.get(task_id)
        if last and last.status == status:
            return last
        await asyncio.sleep(interval)
    return last


async def mock_run_for_task(self, task: str) -> list[ToolResult]:
    return [ToolResult("mock", True, f"mock research for {task[:40]}")]
