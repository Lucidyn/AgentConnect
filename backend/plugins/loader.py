"""Plugin loader — load agents and tools from manifest.yaml or built-in defaults."""

from __future__ import annotations

import importlib
import logging
from pathlib import Path
from typing import Any

import yaml

from backend.agents.registry import BUILTIN_AGENTS
from backend.config import settings
from backend.core.agent import Agent
from backend.tools.arxiv import ArxivTool
from backend.tools.base import Tool
from backend.tools.github import GitHubTool
from backend.tools.http import HttpTool
from backend.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)

_BUILTIN_TOOLS: dict[str, type[Tool]] = {
    "arxiv": ArxivTool,
    "github": GitHubTool,
    "http": HttpTool,
}

REQUIRED_ENTRY_FIELDS = ("name", "module", "class")


def _import_class(module_path: str, class_name: str) -> type:
    module = importlib.import_module(module_path)
    return getattr(module, class_name)


def _load_manifest() -> dict[str, Any] | None:
    path = Path(settings.plugins_manifest)
    if not path.exists():
        return None
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_manifest_entries(section: str) -> list[dict[str, Any]]:
    manifest = _load_manifest()
    if not manifest:
        return []
    entries = manifest.get(section) or []
    return [entry for entry in entries if entry.get("enabled", True)]


def _parse_enabled(env_value: str) -> set[str] | None:
    if not env_value.strip():
        return None
    return {name.strip().lower() for name in env_value.split(",") if name.strip()}


def _entry_config(entry: dict[str, Any]) -> dict[str, Any]:
    skip = {"name", "module", "class", "enabled"}
    return {k: v for k, v in entry.items() if k not in skip}


def _validate_entry(entry: dict[str, Any], kind: str) -> str | None:
    for field in REQUIRED_ENTRY_FIELDS:
        if not entry.get(field):
            return f"Missing '{field}' in {kind} entry"
    return None


def load_agent_plugins(enabled: str = "") -> tuple[list[type[Agent]], dict[str, dict[str, Any]]]:
    enabled_names = _parse_enabled(enabled or settings.enabled_agents)
    manifest = _load_manifest()
    classes: list[type[Agent]] = []
    configs: dict[str, dict[str, Any]] = {}
    seen: set[str] = set()

    if manifest and "agents" in manifest:
        for entry in manifest["agents"]:
            err = _validate_entry(entry, "agent")
            if err:
                logger.warning("Invalid agent entry: %s", err)
                continue
            if not entry.get("enabled", True):
                continue
            name = entry["name"].lower()
            if name in seen:
                logger.warning("Duplicate agent plugin: %s", name)
                continue
            if enabled_names and name not in enabled_names:
                continue
            try:
                cls = _import_class(entry["module"], entry["class"])
                if not issubclass(cls, Agent):
                    raise TypeError(f"{entry['class']} is not an Agent subclass")
                classes.append(cls)
                configs[name] = _entry_config(entry)
                seen.add(name)
                logger.info("Loaded agent plugin: %s", name)
            except Exception as exc:
                logger.warning("Failed to load agent %s: %s", name, exc)
        if classes:
            return classes, configs

    registry = BUILTIN_AGENTS
    if enabled_names:
        keys = [n for n in enabled_names if n in registry]
    else:
        keys = list(registry.keys())
    return [registry[n] for n in keys], configs


def load_tool_registry(enabled: str = "") -> ToolRegistry:
    registry = ToolRegistry()
    enabled_names = _parse_enabled(enabled or settings.enabled_tools)
    manifest = _load_manifest()
    loaded = False
    seen: set[str] = set()

    if manifest and "tools" in manifest:
        for entry in manifest["tools"]:
            err = _validate_entry(entry, "tool")
            if err:
                logger.warning("Invalid tool entry: %s", err)
                continue
            if not entry.get("enabled", True):
                continue
            name = entry["name"].lower()
            if name in seen:
                logger.warning("Duplicate tool plugin: %s", name)
                continue
            if enabled_names and name not in enabled_names:
                continue
            try:
                cls = _import_class(entry["module"], entry["class"])
                if not issubclass(cls, Tool):
                    raise TypeError(f"{entry['class']} is not a Tool subclass")
                tool = cls()
                tool.configure(_entry_config(entry))
                registry.register(tool)
                loaded = True
                seen.add(name)
                logger.info("Loaded tool plugin: %s", name)
            except Exception as exc:
                logger.warning("Failed to load tool %s: %s", name, exc)

    if not loaded:
        names = list(_BUILTIN_TOOLS.keys()) if not enabled_names else [
            n for n in enabled_names if n in _BUILTIN_TOOLS
        ]
        for name in names:
            cls = _BUILTIN_TOOLS.get(name)
            if cls:
                tool = cls()
                tool.configure({})
                registry.register(tool)

    return registry


async def load_mcp_tools(registry: ToolRegistry) -> int:
    from backend.tools.mcp_client import register_mcp_server

    total = 0
    for entry in load_manifest_entries("mcp_servers"):
        total += await register_mcp_server(registry, entry)
    return total
