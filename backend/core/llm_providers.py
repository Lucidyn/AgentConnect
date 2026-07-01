"""LLM providers — OpenAI, Anthropic, and OpenAI-compatible APIs."""

from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod
from typing import Any

from openai import AsyncOpenAI

from backend.config import settings

logger = logging.getLogger(__name__)


async def _with_timeout(coro, timeout: float):
    return await asyncio.wait_for(coro, timeout=timeout)


class LLMProvider(ABC):
    name: str = "base"

    @abstractmethod
    async def chat(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        max_tokens: int,
        temperature: float,
    ) -> str: ...


class OpenAIProvider(LLMProvider):
    name = "openai"

    def __init__(self) -> None:
        self._client = AsyncOpenAI(
            api_key=settings.openai_api_key,
            base_url=settings.openai_base_url,
        )

    async def chat(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        max_tokens: int,
        temperature: float,
    ) -> str:
        response = await _with_timeout(
            self._client.chat.completions.create(
                model=settings.openai_model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=temperature,
                max_tokens=max_tokens,
            ),
            settings.llm_timeout_seconds,
        )
        content = response.choices[0].message.content
        return content or ""


class AnthropicProvider(LLMProvider):
    name = "anthropic"

    def __init__(self) -> None:
        import anthropic

        self._client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)

    async def chat(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        max_tokens: int,
        temperature: float,
    ) -> str:
        response = await _with_timeout(
            self._client.messages.create(
                model=settings.anthropic_model,
                max_tokens=max_tokens,
                temperature=temperature,
                system=system_prompt,
                messages=[{"role": "user", "content": user_prompt}],
            ),
            settings.llm_timeout_seconds,
        )
        parts = [block.text for block in response.content if block.type == "text"]
        return "\n".join(parts)


def create_provider() -> LLMProvider | None:
    provider = settings.llm_provider.lower()

    if provider in ("openai", "openai_compatible"):
        if not settings.openai_api_key:
            return None
        return OpenAIProvider()

    if provider == "anthropic":
        if not settings.anthropic_api_key:
            return None
        return AnthropicProvider()

    logger.warning("Unknown LLM provider: %s", provider)
    return None
