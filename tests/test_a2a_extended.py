"""A2A extended endpoint tests."""

from __future__ import annotations

import pytest


@pytest.fixture
def tenant_client(isolated_paths, patch_settings, monkeypatch):
    patch_settings(api_key="legacy-admin-key", multi_tenant=True, enabled_agents="planner")
    from fastapi.testclient import TestClient

    from backend.app import app
    from backend.platform import platform

    async def fake_dispatch(task):
        return None

    monkeypatch.setattr(platform, "_dispatch_task", fake_dispatch)

    with TestClient(app) as client:
        yield client


def test_a2a_tasks_get_and_cancel(tenant_client):
    client = tenant_client
    headers = {"X-API-Key": "legacy-admin-key"}

    send = client.post(
        "/a2a/tasks/send",
        json={"id": "ext-1", "message": {"parts": [{"type": "text", "text": "hello a2a"}]}},
        headers=headers,
    )
    assert send.status_code == 200
    task_id = send.json()["result"]["id"]

    get_res = client.post("/a2a/tasks/get", json={"id": task_id}, headers=headers)
    assert get_res.status_code == 200
    assert get_res.json()["result"]["id"] == task_id

    cancel = client.post("/a2a/tasks/cancel", json={"id": task_id}, headers=headers)
    assert cancel.status_code == 200
    assert cancel.json()["result"]["status"]["state"] in {"cancelled", "completed", "failed", "submitted", "queued"}


def test_a2a_rpc_tasks_get(tenant_client):
    client = tenant_client
    headers = {"X-API-Key": "legacy-admin-key"}
    send = client.post(
        "/a2a/rpc",
        json={
            "jsonrpc": "2.0",
            "id": "rpc-1",
            "method": "tasks/send",
            "params": {
                "id": "rpc-task",
                "message": {"parts": [{"type": "text", "text": "rpc hello"}]},
            },
        },
        headers=headers,
    )
    assert send.status_code == 200
    task_id = send.json()["result"]["id"]

    get_res = client.post(
        "/a2a/rpc",
        json={"jsonrpc": "2.0", "id": "rpc-2", "method": "tasks/get", "params": {"id": task_id}},
        headers=headers,
    )
    assert get_res.status_code == 200
    assert get_res.json()["result"]["id"] == task_id
