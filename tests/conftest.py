import os
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "redis: integration tests requiring a running Redis instance"
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
def api_client(isolated_paths, patch_settings):
    """FastAPI TestClient with isolated DBs and built-in agents only."""
    patch_settings(enabled_agents="planner,research,coder,reviewer")
    from fastapi.testclient import TestClient

    from backend.app import app

    with TestClient(app) as client:
        yield client
