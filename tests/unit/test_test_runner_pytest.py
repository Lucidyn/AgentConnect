"""TestRunner pytest execution tests."""

from __future__ import annotations

import pytest

from backend.agents.test_runner import TestRunnerAgent, is_test_failed


class _Runner(TestRunnerAgent):
    @property
    def plugin_config(self) -> dict:
        return {"pytest_enabled": True, "sandbox": "subprocess", "timeout": 30}


@pytest.fixture
def runner():
    return _Runner.__new__(_Runner)


def test_pytest_passes_valid_test(runner):
    content = """```python
def test_addition():
    assert 1 + 1 == 2
```"""
    result = runner._run_pytest(content)
    assert result is not None
    assert is_test_failed(result) is False
    assert "通过" in result or "PASSED" in result


def test_pytest_fails_bad_assertion(runner):
    content = """```python
def test_bad():
    assert 1 == 2
```"""
    result = runner._run_pytest(content)
    assert result is not None
    assert is_test_failed(result) is True


def test_pytest_skipped_without_test_functions(runner):
    content = """```python
def helper():
    return 1
```"""
    assert runner._run_pytest(content) is None
