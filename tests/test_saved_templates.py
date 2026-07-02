"""Saved template persistence tests."""

import pytest

from backend.core.saved_templates import delete_saved, get_saved, list_saved, save_template


@pytest.mark.asyncio
async def test_save_and_list_templates(tmp_path, monkeypatch):
    saved_dir = tmp_path / "saved_templates"
    monkeypatch.setattr(
        "backend.core.saved_templates.settings.saved_templates_dir",
        str(saved_dir),
    )
    payload = save_template(
        name="My Plan",
        plan={
            "summary": "Test {task}",
            "assignments": [{"id": "t1", "agent": "Research", "task": "Go", "depends_on": []}],
        },
    )
    assert payload["id"]
    items = list_saved()
    assert any(item["id"] == payload["id"] for item in items)
    loaded = get_saved(payload["id"])
    assert loaded["plan"]["assignments"][0]["agent"] == "Research"
    assert delete_saved(payload["id"]) is True
    assert get_saved(payload["id"]) is None
