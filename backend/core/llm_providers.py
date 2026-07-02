"""LLM providers — OpenAI, Anthropic, and OpenAI-compatible APIs."""

from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

from openai import AsyncOpenAI

from backend.config import settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ChatResult:
    text: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    model: str = ""


def _usage_from_openai(response, model: str = "") -> ChatResult:
    content = response.choices[0].message.content or ""
    usage = getattr(response, "usage", None)
    prompt = int(getattr(usage, "prompt_tokens", 0) or 0)
    completion = int(getattr(usage, "completion_tokens", 0) or 0)
    total = int(getattr(usage, "total_tokens", 0) or 0) or prompt + completion
    return ChatResult(
        text=content,
        prompt_tokens=prompt,
        completion_tokens=completion,
        total_tokens=total,
        model=model or getattr(response, "model", "") or "",
    )


def _usage_from_anthropic(response, model: str = "") -> ChatResult:
    parts = [block.text for block in response.content if block.type == "text"]
    text = "\n".join(parts)
    usage = getattr(response, "usage", None)
    prompt = int(getattr(usage, "input_tokens", 0) or 0)
    completion = int(getattr(usage, "output_tokens", 0) or 0)
    return ChatResult(
        text=text,
        prompt_tokens=prompt,
        completion_tokens=completion,
        total_tokens=prompt + completion,
        model=model or settings.anthropic_model,
    )


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
    ) -> ChatResult: ...

    async def chat_json(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        max_tokens: int,
        temperature: float,
    ) -> ChatResult:
        """Structured JSON output when supported; otherwise plain chat."""
        return await self.chat(
            system_prompt,
            user_prompt,
            max_tokens=max_tokens,
            temperature=temperature,
        )

    async def chat_stream(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        max_tokens: int,
        temperature: float,
    ) -> AsyncIterator[str]:
        result = await self.chat(
            system_prompt,
            user_prompt,
            max_tokens=max_tokens,
            temperature=temperature,
        )
        if result.text:
            yield result.text

    async def chat_stream_with_usage(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        max_tokens: int,
        temperature: float,
    ) -> tuple[AsyncIterator[str], ChatResult | None]:
        """Default: stream text only; providers may override with usage on completion."""
        result = await self.chat(
            system_prompt,
            user_prompt,
            max_tokens=max_tokens,
            temperature=temperature,
        )

        async def _iter():
            if result.text:
                yield result.text

        return _iter(), result


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
    ) -> ChatResult:
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
        return _usage_from_openai(response, settings.openai_model)

    async def chat_stream_with_usage(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        max_tokens: int,
        temperature: float,
    ) -> tuple[AsyncIterator[str], ChatResult | None]:
        stream = await _with_timeout(
            self._client.chat.completions.create(
                model=settings.openai_model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=temperature,
                max_tokens=max_tokens,
                stream=True,
                stream_options={"include_usage": True},
            ),
            settings.llm_timeout_seconds,
        )
        holder: dict[str, ChatResult | None] = {"usage": None}
        parts: list[str] = []

        async def _iter():
            async for chunk in stream:
                delta = chunk.choices[0].delta.content
                if delta:
                    parts.append(delta)
                    yield delta
                usage = getattr(chunk, "usage", None)
                if usage:
                    prompt = int(getattr(usage, "prompt_tokens", 0) or 0)
                    completion = int(getattr(usage, "completion_tokens", 0) or 0)
                    total = int(getattr(usage, "total_tokens", 0) or 0) or prompt + completion
                    holder["usage"] = ChatResult(
                        text="".join(parts),
                        prompt_tokens=prompt,
                        completion_tokens=completion,
                        total_tokens=total,
                        model=settings.openai_model,
                    )

        return _iter(), holder

    async def chat_stream(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        max_tokens: int,
        temperature: float,
    ) -> AsyncIterator[str]:
        stream_iter, _ = await self.chat_stream_with_usage(
            system_prompt,
            user_prompt,
            max_tokens=max_tokens,
            temperature=temperature,
        )
        async for chunk in stream_iter:
            yield chunk

    async def chat_json(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        max_tokens: int,
        temperature: float,
    ) -> ChatResult:
        response = await _with_timeout(
            self._client.chat.completions.create(
                model=settings.openai_model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=temperature,
                max_tokens=max_tokens,
                response_format={"type": "json_object"},
            ),
            settings.llm_timeout_seconds,
        )
        return _usage_from_openai(response, settings.openai_model)


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
    ) -> ChatResult:
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
        return _usage_from_anthropic(response, settings.anthropic_model)

    async def chat_stream_with_usage(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        max_tokens: int,
        temperature: float,
    ) -> tuple[AsyncIterator[str], ChatResult | None]:
        holder: dict[str, ChatResult | None] = {"usage": None}
        parts: list[str] = []

        async def _iter():
            async with self._client.messages.stream(
                model=settings.anthropic_model,
                max_tokens=max_tokens,
                temperature=temperature,
                system=system_prompt,
                messages=[{"role": "user", "content": user_prompt}],
            ) as stream:
                async for text in stream.text_stream:
                    if text:
                        parts.append(text)
                        yield text
                final = await stream.get_final_message()
                usage = _usage_from_anthropic(final, settings.anthropic_model)
                holder["usage"] = ChatResult(
                    text="".join(parts),
                    prompt_tokens=usage.prompt_tokens,
                    completion_tokens=usage.completion_tokens,
                    total_tokens=usage.total_tokens,
                    model=settings.anthropic_model,
                )

        return _iter(), holder


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
