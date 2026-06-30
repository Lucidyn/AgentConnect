"""HTTP API smoke tests."""

import pytest


def test_health(api_client):
    resp = api_client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["agents"] >= 4
    assert "agent_runtimes" in data


def test_list_agents(api_client):
    resp = api_client.get("/agents")
    assert resp.status_code == 200
    names = {a["name"] for a in resp.json()["agents"]}
    assert "Planner" in names
    assert "Coder" in names


def test_submit_and_get_task(api_client):
    resp = api_client.post("/tasks", json={"task": "hello api test"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["task_id"]
    assert body["status"] in ("submitted", "queued")

    task_id = body["task_id"]
    get_resp = api_client.get(f"/tasks/{task_id}")
    assert get_resp.status_code == 200
    assert get_resp.json()["task"]["id"] == task_id


def test_plan_without_task_id_empty(api_client):
    resp = api_client.get("/plan")
    assert resp.status_code == 200
    # No tasks yet in isolated DB — plan may be null
    assert "plan" in resp.json()


def test_task_result_without_id_processing(api_client):
    resp = api_client.get("/tasks/result")
    assert resp.status_code == 200
    assert resp.json()["status"] == "processing"
