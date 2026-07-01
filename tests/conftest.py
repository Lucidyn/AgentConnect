import os
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tests.helpers import mock_run_for_task


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "redis: integration tests requiring a running Redis instance"
    )
    config.addinivalue_line(
        "markers", "postgres: integration tests requiring PostgreSQL (DATABASE_URL)"
    )


@pytest.fixture
def db_path():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    yield path
    if os.path.exists(path):
        os.unlink(path)


@pytest.fixture
def isolated_paths(tmp_path, monkeypatch):
    """Point task/registry DBs at temp files for integration tests."""
    tasks_db = str(tmp_path / "tasks.db")
    registry_db = str(tmp_path / "registry.db")
    monkeypatch.setattr("backend.config.settings.tasks_db_path", tasks_db)
    monkeypatch.setattr("backend.config.settings.registry_db_path", registry_db)
    monkeypatch.setattr("backend.config.settings.database_url", "")
    monkeypatch.setattr("backend.config.settings.use_redis", False)
    monkeypatch.setattr("backend.config.settings.use_qdrant", False)
    monkeypatch.setattr("backend.config.settings.message_reliability", True)
    return {"tasks": tasks_db, "registry": registry_db}


@pytest.fixture
def patch_settings(monkeypatch):
    """Patch backend.config.settings attributes consistently."""

    def _patch(**kwargs):
        for key, value in kwargs.items():
            monkeypatch.setattr(f"backend.config.settings.{key}", value)

    return _patch


@pytest.fixture
def mock_tools(monkeypatch):
    """Patch ToolRegistry.run_for_task with a fast mock (no external APIs)."""
    from backend.tools.registry import ToolRegistry

    monkeypatch.setattr(ToolRegistry, "run_for_task", mock_run_for_task)


@pytest.fixture
def api_client(isolated_paths, patch_settings):
    """FastAPI TestClient with isolated DBs and built-in agents only."""
    patch_settings(enabled_agents="planner,research,coder,reviewer")
    from fastapi.testclient import TestClient

    from backend.app import app

    with TestClient(app) as client:
        yield client


@pytest.fixture
async def planner_stack(isolated_paths, patch_settings):
    """Started Planner with in-memory bus and isolated stores."""
    patch_settings(enabled_agents="planner,research,coder,reviewer")
    stack = await _build_planner_stack(isolated_paths)
    yield stack
    await stack.close()


@pytest.fixture
async def planner_stack_factory(isolated_paths, patch_settings):
    """Factory for planner stacks with custom settings."""
    stacks = []

    async def _create(**settings_kwargs):
        enabled = settings_kwargs.pop("enabled_agents", "planner,research,coder,reviewer")
        patch_settings(enabled_agents=enabled, **settings_kwargs)
        stack = await _build_planner_stack(isolated_paths)
        stacks.append(stack)
        return stack

    yield _create
    for stack in stacks:
        await stack.close()


async def _build_planner_stack(isolated_paths):
    from dataclasses import dataclass

    from backend.agents.planner import PlannerAgent
    from backend.core.llm import LLMClient
    from backend.core.message_bus import InMemoryMessageBus
    from backend.core.registry import AgentRegistry
    from backend.core.services import AgentServices
    from backend.core.shared_memory import InMemorySharedMemory
    from backend.core.task_store import TaskStore
    from backend.tools.registry import ToolRegistry

    @dataclass
    class PlannerStack:
        planner: PlannerAgent
        store: TaskStore
        bus: InMemoryMessageBus
        registry: AgentRegistry

        async def close(self) -> None:
            await self.planner.stop()
            await self.bus.disconnect()
            await self.store.disconnect()
            await self.registry.disconnect()

    registry = AgentRegistry(isolated_paths["registry"])
    await registry.connect()
    store = TaskStore(isolated_paths["tasks"])
    await store.connect()
    bus = InMemoryMessageBus()
    await bus.connect()
    services = AgentServices(
        bus=bus,
        registry=registry,
        llm=LLMClient(),
        shared_memory=InMemorySharedMemory(),
        tools=ToolRegistry(),
        task_store=store,
    )
    planner = PlannerAgent(services)
    await planner.register()
    await planner.start()
    return PlannerStack(planner=planner, store=store, bus=bus, registry=registry)
