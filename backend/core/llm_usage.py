"""LLM token usage tracking per task."""

from __future__ import annotations

from pydantic import BaseModel, Field


class LLMUsageEntry(BaseModel):
    agent: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    model: str = ""


def merge_usage(entries: list[LLMUsageEntry]) -> dict[str, int]:
    prompt = sum(item.prompt_tokens for item in entries)
    completion = sum(item.completion_tokens for item in entries)
    total = sum(item.total_tokens for item in entries) or prompt + completion
    return {
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "total_tokens": total,
        "calls": len(entries),
    }


def estimate_cost(
    usage: dict[str, int],
    *,
    input_per_1k: float,
    output_per_1k: float,
) -> float:
    prompt = usage.get("prompt_tokens", 0)
    completion = usage.get("completion_tokens", 0)
    return (prompt / 1000.0) * input_per_1k + (completion / 1000.0) * output_per_1k
