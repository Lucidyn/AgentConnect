"""Plugin manifest validation tests."""

from backend.plugins.validate import validate_manifest


def test_validate_builtin_manifest():
    report = validate_manifest()
    assert report["manifest_path"]
    assert isinstance(report["agents"], list)
    assert isinstance(report["tools"], list)
    enabled_agents = [a for a in report["agents"] if a.get("enabled")]
    assert enabled_agents
    assert all(a["ok"] for a in enabled_agents)
