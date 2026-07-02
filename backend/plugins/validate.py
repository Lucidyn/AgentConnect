"""Manifest validation — check plugin entries before load."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from backend.config import settings
from backend.core.agent import Agent
from backend.plugins.loader import REQUIRED_ENTRY_FIELDS, _import_class
from backend.tools.base import Tool


def _load_manifest() -> dict[str, Any] | None:
    path = Path(settings.plugins_manifest)
    if not path.exists():
        return None
    with path.open(encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def validate_manifest() -> dict[str, Any]:
    """Return structured validation report for plugins/manifest.yaml."""
    manifest = _load_manifest()
    if manifest is None:
        return {
            "valid": False,
            "manifest_path": settings.plugins_manifest,
            "errors": [f"Manifest not found: {settings.plugins_manifest}"],
            "agents": [],
            "tools": [],
        }

    errors: list[str] = []
    agents: list[dict[str, Any]] = []
    tools: list[dict[str, Any]] = []
    seen_agents: set[str] = set()
    seen_tools: set[str] = set()

    for entry in manifest.get("agents") or []:
        name = str(entry.get("name", "")).lower()
        row: dict[str, Any] = {"name": name, "enabled": entry.get("enabled", True), "ok": True}
        for field in REQUIRED_ENTRY_FIELDS:
            if not entry.get(field):
                msg = f"agent '{name or '?'}': missing '{field}'"
                errors.append(msg)
                row["ok"] = False
        if name in seen_agents:
            errors.append(f"duplicate agent name: {name}")
            row["ok"] = False
        seen_agents.add(name)
        if row["ok"] and entry.get("enabled", True):
            try:
                cls = _import_class(entry["module"], entry["class"])
                if not issubclass(cls, Agent):
                    raise TypeError(f"{entry['class']} is not an Agent subclass")
                row["class"] = f"{entry['module']}.{entry['class']}"
            except Exception as exc:
                errors.append(f"agent '{name}': {exc}")
                row["ok"] = False
        agents.append(row)

    for entry in manifest.get("tools") or []:
        name = str(entry.get("name", "")).lower()
        row = {"name": name, "enabled": entry.get("enabled", True), "ok": True}
        for field in REQUIRED_ENTRY_FIELDS:
            if not entry.get(field):
                msg = f"tool '{name or '?'}': missing '{field}'"
                errors.append(msg)
                row["ok"] = False
        if name in seen_tools:
            errors.append(f"duplicate tool name: {name}")
            row["ok"] = False
        seen_tools.add(name)
        if row["ok"] and entry.get("enabled", True):
            try:
                cls = _import_class(entry["module"], entry["class"])
                if not issubclass(cls, Tool):
                    raise TypeError(f"{entry['class']} is not a Tool subclass")
                row["class"] = f"{entry['module']}.{entry['class']}"
            except Exception as exc:
                errors.append(f"tool '{name}': {exc}")
                row["ok"] = False
        tools.append(row)

    return {
        "valid": not errors,
        "manifest_path": settings.plugins_manifest,
        "errors": errors,
        "agents": agents,
        "tools": tools,
    }
