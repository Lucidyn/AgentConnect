"""API authentication tests."""

from __future__ import annotations

import pytest


@pytest.fixture
def api_client_with_key(isolated_paths, patch_settings):
    patch_settings(api_key="secret-test-key", enabled_agents="planner,research,coder,reviewer")
    from fastapi.testclient import TestClient

    from backend.app import app

    with TestClient(app) as client:
        yield client


def test_submit_without_key_when_api_key_set(api_client_with_key):
    res = api_client_with_key.post("/tasks", json={"task": "hello"})
    assert res.status_code == 401


def test_submit_with_valid_key(api_client_with_key, monkeypatch):
    from backend.platform import platform

    async def fake_dispatch(task):
        return None

    monkeypatch.setattr(platform, "_dispatch_task", fake_dispatch)

    res = api_client_with_key.post(
        "/tasks",
        json={"task": "hello"},
        headers={"X-API-Key": "secret-test-key"},
    )
    assert res.status_code == 200
    assert res.json()["task_id"]


def test_get_task_requires_key_when_configured(api_client_with_key, monkeypatch):
    from backend.platform import platform

    async def fake_dispatch(task):
        return None

    monkeypatch.setattr(platform, "_dispatch_task", fake_dispatch)

    create = api_client_with_key.post(
        "/tasks",
        json={"task": "secret task"},
        headers={"X-API-Key": "secret-test-key"},
    )
    task_id = create.json()["task_id"]

    denied = api_client_with_key.get(f"/tasks/{task_id}")
    assert denied.status_code == 401

    allowed = api_client_with_key.get(
        f"/tasks/{task_id}",
        headers={"X-API-Key": "secret-test-key"},
    )
    assert allowed.status_code == 200


def test_task_input_max_length(api_client):
    res = api_client.post("/tasks", json={"task": "x" * 9000})
    assert res.status_code == 422


def test_approval_invalid_action(api_client):
    res = api_client.post(
        "/tasks/nonexistent/approve",
        json={"action": "invalid"},
    )
    assert res.status_code == 422


def test_agents_requires_key_when_configured(api_client_with_key):
    denied = api_client_with_key.get("/agents")
    assert denied.status_code == 401

    allowed = api_client_with_key.get(
        "/agents",
        headers={"X-API-Key": "secret-test-key"},
    )
    assert allowed.status_code == 200


def test_tools_and_metrics_require_key_when_configured(api_client_with_key):
    for path in ("/tools", "/metrics"):
        denied = api_client_with_key.get(path)
        assert denied.status_code == 401

        allowed = api_client_with_key.get(
            path,
            headers={"X-API-Key": "secret-test-key"},
        )
        assert allowed.status_code == 200
