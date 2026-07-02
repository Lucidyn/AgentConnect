"""Per-agent LLM model routing."""

from __future__ import annotations

from backend.config import settings


def resolve_model(agent: str, role: str, plugin_configs: dict | None = None) -> str | None:
    """Return model override for an agent, or None for provider default."""
    configs = plugin_configs or {}
    cfg = configs.get(agent.lower(), {})
    explicit = str(cfg.get("llm_model") or cfg.get("model") or "").strip()
    if explicit and not any(ch in explicit for ch in ("+", "OCR", "YOLO", "LangGraph")):
        return explicit

    tier = str(cfg.get("model_tier") or "").lower()
    if not tier:
        tier = _default_tier_for_role(role)

    if tier == "cheap" and settings.llm_cheap_model:
        return settings.llm_cheap_model
    if tier == "premium" and settings.llm_premium_model:
        return settings.llm_premium_model
    if tier == "research" and settings.llm_research_model:
        return settings.llm_research_model
    if tier == "coder" and settings.llm_coder_model:
        return settings.llm_coder_model
    return None


def _default_tier_for_role(role: str) -> str:
    mapping = {
        "planner": "cheap",
        "researcher": "cheap",
        "developer": "premium",
        "writer": "premium",
        "analyst": "cheap",
        "reviewer": "cheap",
        "tester": "cheap",
    }
    return mapping.get(role, "cheap")
