"""API tests for templates and orchestration submission."""

from __future__ import annotations


def test_list_templates(api_client):
    res = api_client.get("/templates")
    assert res.status_code == 200
    data = res.json()
    assert any(item["id"] == "hybrid_report" for item in data["templates"])


def test_validate_custom_plan(api_client):
    body = {
        "task": "demo",
        "custom_plan": {
            "summary": "自定义",
            "assignments": [
                {"id": "t1", "agent": "Research", "task": "调研", "depends_on": []},
                {"id": "t2", "agent": "Writer", "task": "写作", "depends_on": ["t1"]},
            ],
        },
    }
    res = api_client.post("/templates/validate", json=body)
    assert res.status_code == 200
    assert res.json()["valid"] is True


def test_submit_with_template_id(api_client, monkeypatch):
    from backend.platform import platform

    async def fake_dispatch(task):
        return None

    monkeypatch.setattr(platform, "_dispatch_task", fake_dispatch)

    res = api_client.post(
        "/tasks",
        json={
            "task": "写一篇产品介绍并翻译为英文",
            "template_id": "research_write_translate",
        },
    )
    assert res.status_code == 200
    task_id = res.json()["task_id"]
    task = api_client.get(f"/tasks/{task_id}").json()["task"]
    assert task["context"]["template_id"] == "research_write_translate"
    assert task["context"]["collaboration_mode"] == "planner"
