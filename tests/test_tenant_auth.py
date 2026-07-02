"""Multi-tenant auth and RBAC tests."""

from __future__ import annotations

import asyncio

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
        yield client, platform


def test_legacy_key_is_default_tenant_admin(tenant_client):
    client, _platform = tenant_client
    res = client.post(
        "/tasks",
        json={"task": "hello"},
        headers={"X-API-Key": "legacy-admin-key"},
    )
    assert res.status_code == 200
    task_id = res.json()["task_id"]
    detail = client.get(
        f"/tasks/{task_id}",
        headers={"X-API-Key": "legacy-admin-key"},
    )
    assert detail.status_code == 200


def test_tenant_isolation(tenant_client):
    client, _platform = tenant_client
    headers = {"X-API-Key": "legacy-admin-key"}

    create_tenant = client.post(
        "/admin/tenants",
        json={"tenant_id": "acme", "name": "Acme Corp"},
        headers=headers,
    )
    assert create_tenant.status_code == 200

    key_res = client.post(
        "/admin/tenants/acme/keys",
        json={"name": "ops", "role": "operator"},
        headers=headers,
    )
    assert key_res.status_code == 200
    acme_key = key_res.json()["key"]

    create = client.post(
        "/tasks",
        json={"task": "tenant-a task"},
        headers=headers,
    )
    task_id = create.json()["task_id"]

    denied = client.get(
        f"/tasks/{task_id}",
        headers={"X-API-Key": acme_key},
    )
    assert denied.status_code == 404

    allowed = client.get(f"/tasks/{task_id}", headers=headers)
    assert allowed.status_code == 200


def test_viewer_cannot_submit_tasks(tenant_client):
    client, platform = tenant_client
    from backend.models.auth import Role

    raw, _meta = asyncio.run(
        platform.tenant_store.create_api_key("default", name="viewer", role=Role.VIEWER)
    )
    res = client.post(
        "/tasks",
        json={"task": "blocked"},
        headers={"X-API-Key": raw},
    )
    assert res.status_code == 403


def test_admin_can_create_tenant_key(tenant_client):
    client, _platform = tenant_client
    res = client.post(
        "/admin/tenants/default/keys",
        json={"name": "ops-key", "role": "operator"},
        headers={"X-API-Key": "legacy-admin-key"},
    )
    assert res.status_code == 200
    assert res.json()["key"]
    assert res.json()["meta"]["role"] == "operator"


def test_a2a_tasks_send_accepts_text_message(tenant_client, monkeypatch):
    client, platform = tenant_client

    async def fake_dispatch(task):
        return None

    monkeypatch.setattr(platform, "_dispatch_task", fake_dispatch)

    res = client.post(
        "/a2a/tasks/send",
        json={
            "id": "a2a-1",
            "message": {"role": "user", "parts": [{"type": "text", "text": "Summarize AI trends"}]},
        },
        headers={"X-API-Key": "legacy-admin-key"},
    )
    assert res.status_code == 200
    assert res.json()["result"]["id"]
