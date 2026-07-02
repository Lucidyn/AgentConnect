"""A2A streaming tests."""

from __future__ import annotations

import pytest

from backend.a2a.protocol import task_to_a2a_stream_event
from backend.models.task import TaskRecord, TaskStatus


def test_task_to_a2a_stream_event_partial():
    task = TaskRecord(id="t1", input="hello", status=TaskStatus.RUNNING, tenant_id="default")
    event = task_to_a2a_stream_event(
        task,
        extra={"partial_result": "streaming...", "queue_position": 0},
    )
    assert event["type"] == "status-update"
    assert event["task_id"] == "t1"
    assert event["status"]["state"] == "running"
    parts = event["status"]["message"]["parts"]
    assert any(p.get("text") == "streaming..." for p in parts)


@pytest.fixture
def tenant_client(isolated_paths, patch_settings, monkeypatch):
    patch_settings(api_key="legacy-admin-key", multi_tenant=True, enabled_agents="planner")
    from fastapi.testclient import TestClient

    from backend.app import app
    from backend.platform import platform

    async def fake_dispatch(task):
        await platform.task_store.save_result(task.id, "stream done")
        return None

    monkeypatch.setattr(platform, "_dispatch_task", fake_dispatch)

    with TestClient(app) as client:
        yield client


def test_a2a_agent_card_lists_stream(tenant_client):
    res = tenant_client.get("/a2a/agent-card", headers={"X-API-Key": "legacy-admin-key"})
    assert res.status_code == 200
    assert "tasks/stream" in res.json()["methods"]


def test_a2a_tasks_stream_endpoint(tenant_client):
    client = tenant_client
    headers = {"X-API-Key": "legacy-admin-key"}
    send = client.post(
        "/a2a/tasks/send",
        json={"id": "stream-1", "message": {"parts": [{"type": "text", "text": "stream me"}]}},
        headers=headers,
    )
    assert send.status_code == 200
    task_id = send.json()["result"]["id"]

    stream = client.get(f"/a2a/tasks/{task_id}/stream", headers=headers)
    assert stream.status_code == 200
    assert "text/event-stream" in stream.headers["content-type"]
    assert "status-update" in stream.text
    assert task_id in stream.text
