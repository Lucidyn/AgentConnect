"""LLM client tests."""

import pytest

from backend.core.llm import LLMClient


@pytest.mark.asyncio
async def test_llm_fallback_without_key(monkeypatch):
    monkeypatch.setattr("backend.core.llm_providers.settings.openai_api_key", "")
    monkeypatch.setattr("backend.core.llm_providers.settings.anthropic_api_key", "")
    monkeypatch.setattr("backend.core.llm_providers.settings.llm_provider", "openai")

    client = LLMClient()
    assert client.available is False
    assert client.provider_name == "fallback"

    result = await client.chat("sys", "user", fallback="mock")
    assert result == "mock"
