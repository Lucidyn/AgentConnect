"""Tenant isolation for messages, traces, and memory."""

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
        yield client, platform


def test_messages_filtered_by_tenant(tenant_client):
    client, platform = tenant_client
    headers = {"X-API-Key": "legacy-admin-key"}

    assert client.post(
        "/admin/tenants",
        json={"tenant_id": "acme", "name": "Acme"},
        headers=headers,
    ).status_code == 200

    key_res = client.post(
        "/admin/tenants/acme/keys",
        json={"name": "ops", "role": "operator"},
        headers=headers,
    )
    acme_key = key_res.json()["key"]

    create = client.post("/tasks", json={"task": "hello"}, headers=headers)
    assert create.status_code == 200
    task_id = create.json()["task_id"]
    assert client.get(f"/tasks/{task_id}", headers=headers).status_code == 200

    from backend.models.message import Message, MessageType

    platform._message_log.append(
        Message(
            from_agent="User",
            to_agent="Planner",
            content="hello",
            message_type=MessageType.TASK,
            task_id=task_id,
        )
    )

    default_msgs = client.get("/messages", headers=headers)
    assert default_msgs.status_code == 200
    assert len(default_msgs.json()["messages"]) >= 1

    acme_msgs = client.get("/messages", headers={"X-API-Key": acme_key})
    assert acme_msgs.status_code == 200
    assert len(acme_msgs.json()["messages"]) == 0


def test_trace_requires_tenant_access(tenant_client):
    client, _platform = tenant_client
    headers = {"X-API-Key": "legacy-admin-key"}
    create = client.post("/tasks", json={"task": "trace me"}, headers=headers)
    task_id = create.json()["task_id"]
    messages = client.get(f"/tasks/{task_id}/messages", headers=headers).json()["messages"]
    if not messages:
        pytest.skip("No messages logged for task")
    trace_id = messages[0]["trace_id"]
    assert client.get(f"/traces/{trace_id}", headers=headers).status_code == 200

    client.post("/admin/tenants", json={"tenant_id": "acme", "name": "Acme"}, headers=headers)
    acme_key = client.post(
        "/admin/tenants/acme/keys",
        json={"name": "ops", "role": "operator"},
        headers=headers,
    ).json()["key"]
    assert client.get(f"/traces/{trace_id}", headers={"X-API-Key": acme_key}).status_code == 404


def test_memory_query_respects_tenant(tenant_client):
    client, platform = tenant_client
    import asyncio

    headers = {"X-API-Key": "legacy-admin-key"}

    async def seed_memory():
        await platform.shared_memory.store(
            content="secret alpha",
            agent="Research",
            metadata={"tenant_id": "default"},
            tenant_id="default",
        )
        await platform.shared_memory.store(
            content="secret beta",
            agent="Research",
            metadata={"tenant_id": "acme"},
            tenant_id="acme",
        )

    asyncio.run(seed_memory())

    default_query = client.post(
        "/memory/query",
        json={"query": "secret"},
        headers=headers,
    )
    assert default_query.status_code == 200
    texts = [e["content"] for e in default_query.json()["entries"]]
    assert "secret alpha" in texts
    assert "secret beta" not in texts

    client.post("/admin/tenants", json={"tenant_id": "acme", "name": "Acme"}, headers=headers)
    acme_key = client.post(
        "/admin/tenants/acme/keys",
        json={"name": "ops", "role": "operator"},
        headers=headers,
    ).json()["key"]
    acme_query = client.post(
        "/memory/query",
        json={"query": "secret"},
        headers={"X-API-Key": acme_key},
    )
    texts = [e["content"] for e in acme_query.json()["entries"]]
    assert "secret beta" in texts
    assert "secret alpha" not in texts
