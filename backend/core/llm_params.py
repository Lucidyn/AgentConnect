"""Per-role LLM generation parameters."""

from __future__ import annotations

from backend.config import settings


def llm_params_for_role(role: str) -> dict[str, int | float]:
    """Return max_tokens and temperature tuned for each agent role."""
    defaults: dict[str, dict[str, int | float]] = {
        "planner": {
            "max_tokens": settings.llm_max_tokens_planner,
            "temperature": settings.llm_temperature_planner,
        },
        "researcher": {
            "max_tokens": settings.llm_max_tokens_research,
            "temperature": settings.llm_temperature_default,
        },
        "developer": {
            "max_tokens": settings.llm_max_tokens_coder,
            "temperature": settings.llm_temperature_default,
        },
        "writer": {
            "max_tokens": settings.llm_max_tokens_coder,
            "temperature": settings.llm_temperature_default,
        },
        "analyst": {
            "max_tokens": settings.llm_max_tokens_research,
            "temperature": settings.llm_temperature_default,
        },
        "reviewer": {
            "max_tokens": settings.llm_max_tokens_reviewer,
            "temperature": settings.llm_temperature_default,
        },
        "tester": {
            "max_tokens": settings.llm_max_tokens_reviewer,
            "temperature": settings.llm_temperature_default,
        },
    }
    return defaults.get(
        role,
        {
            "max_tokens": settings.llm_max_tokens_default,
            "temperature": settings.llm_temperature_default,
        },
    )
