"""End-to-end pipeline test with mocked external tools."""

import pytest

from backend.models.task import TaskStatus
from backend.platform import Platform
from tests.helpers import wait_for_task_status


@pytest.mark.asyncio
async def test_full_pipeline_completes(isolated_paths, mock_tools, monkeypatch):
    monkeypatch.setattr("backend.config.settings.max_concurrent_tasks", 1)

    platform = Platform()
    await platform.start()
    try:
        task, message = await platform.submit_task("build a tiny health API")
        assert message is not None

        final = await wait_for_task_status(
            platform.task_store, task.id, TaskStatus.COMPLETED, timeout=12.0
        )

        assert final is not None
        assert final.status == TaskStatus.COMPLETED
        assert final.plan is not None
        statuses = {a["id"]: a["status"] for a in final.plan["assignments"]}
        assert all(status == "done" for status in statuses.values())
        assert statuses.get("t1") == "done"
        assert final.result
    finally:
        await platform.stop()
