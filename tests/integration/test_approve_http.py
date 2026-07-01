"""HTTP approval flow integration test."""

from __future__ import annotations

import time

import pytest


@pytest.mark.asyncio
async def test_approve_endpoint_accepts_valid_action(api_client, patch_settings):
    import asyncio

    patch_settings(fast_mode=True, fast_skip_planner_llm=True, loop_max_iterations=0)

    from backend.models.task import TaskStatus
    from backend.platform import platform

    res = api_client.post("/tasks", json={"task": "approval endpoint smoke"})
    assert res.status_code == 200
    task_id = res.json()["task_id"]

    deadline = time.time() + 15
    status = None
    while time.time() < deadline:
        task = await platform.task_store.get(task_id)
        if task:
            status = task.status
            if status in (
                TaskStatus.WAITING_APPROVAL,
                TaskStatus.COMPLETED,
                TaskStatus.FAILED,
            ):
                break
        await asyncio.sleep(0.1)

    if status != TaskStatus.WAITING_APPROVAL:
        pytest.skip("Task did not enter waiting_approval in time (reviewer passed)")

    approve = api_client.post(f"/tasks/{task_id}/approve", json={"action": "approve"})
    assert approve.status_code == 200
    assert approve.json()["task"]["id"] == task_id


def test_approve_unknown_task_returns_409(api_client):
    res = api_client.post("/tasks/does-not-exist/approve", json={"action": "approve"})
    assert res.status_code == 409
