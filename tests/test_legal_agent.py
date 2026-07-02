"""Legal custom agent plugin tests."""

from __future__ import annotations


def test_legal_agent_metadata():
    from plugins.legal.agent import LegalAgent

    assert LegalAgent.name == "Legal"
    assert "contract_review" in LegalAgent.capabilities


def test_legal_agent_in_manifest():
    from backend.plugins.loader import load_agent_plugins

    classes, configs = load_agent_plugins()
    names = {cls.name for cls in classes}
    assert "Legal" in names
    assert configs.get("legal", {}).get("jurisdiction") == "中国大陆"
