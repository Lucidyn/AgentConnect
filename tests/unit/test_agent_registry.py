"""Built-in agent registry tests."""

from backend.agents.registry import BUILTIN_AGENTS


def test_builtin_agents_registry():
    assert set(BUILTIN_AGENTS) == {
        "planner",
        "research",
        "coder",
        "writer",
        "analyst",
        "translator",
        "test_runner",
        "reviewer",
    }
    assert len(BUILTIN_AGENTS) == 8
