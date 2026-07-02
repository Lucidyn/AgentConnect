"""Plugin loader tests."""

import pytest
import yaml

from backend.plugins.loader import load_agent_plugins, load_tool_registry


def test_load_builtin_agents():
    classes, configs = load_agent_plugins()
    names = {cls.__name__ for cls in classes}
    assert "PlannerAgent" in names
    assert "ResearchAgent" in names


def test_load_agents_from_manifest(tmp_path, monkeypatch):
    manifest = {
        "agents": [
            {
                "name": "planner",
                "module": "backend.agents.planner",
                "class": "PlannerAgent",
                "enabled": True,
                "llm_model": "gpt-4o",
            }
        ],
        "tools": [],
    }
    path = tmp_path / "manifest.yaml"
    path.write_text(yaml.dump(manifest), encoding="utf-8")
    monkeypatch.setattr("backend.plugins.loader.settings.plugins_manifest", str(path))

    classes, configs = load_agent_plugins()
    assert len(classes) == 1
    assert classes[0].__name__ == "PlannerAgent"
    assert configs["planner"]["llm_model"] == "gpt-4o"


def test_manifest_validation_skips_invalid(tmp_path, monkeypatch):
    manifest = {
        "agents": [
            {"name": "bad", "enabled": True},
            {
                "name": "planner",
                "module": "backend.agents.planner",
                "class": "PlannerAgent",
                "enabled": True,
            },
        ],
    }
    path = tmp_path / "manifest.yaml"
    path.write_text(yaml.dump(manifest), encoding="utf-8")
    monkeypatch.setattr("backend.plugins.loader.settings.plugins_manifest", str(path))

    classes, _ = load_agent_plugins()
    assert len(classes) == 1


def test_vision_plugin_import():
    from plugins.vision.agent import VisionAgent

    assert VisionAgent.name == "Vision"
    assert "ocr" in VisionAgent.capabilities


def test_load_tools():
    registry = load_tool_registry()
    names = {t["name"] for t in registry.list_tools()}
    assert "arxiv" in names
    assert "github" in names
