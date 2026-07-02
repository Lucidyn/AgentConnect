"""LLM client — delegates to configured provider with rule-based fallback."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable

from backend.config import settings
from backend.core.llm_params import llm_params_for_role
from backend.core.llm_providers import ChatResult, create_provider
from backend.core.llm_usage import LLMUsageEntry
from backend.core.metrics import LLM_REQUESTS, LLM_TOKENS

logger = logging.getLogger(__name__)

RecordUsage = Callable[[LLMUsageEntry], Awaitable[None]]


class LLMClient:
    def __init__(self) -> None:
        self._provider = create_provider()

    @property
    def available(self) -> bool:
        return self._provider is not None

    @property
    def provider_name(self) -> str:
        if self._provider:
            return self._provider.name
        return settings.llm_provider if self._has_credentials() else "fallback"

    def _has_credentials(self) -> bool:
        if settings.llm_provider == "anthropic":
            return bool(settings.anthropic_api_key)
        return bool(settings.openai_api_key)

    def _record_token_metrics(self, provider_name: str, result: ChatResult) -> None:
        if result.prompt_tokens:
            LLM_TOKENS.labels(provider=provider_name, direction="prompt").inc(
                result.prompt_tokens
            )
        if result.completion_tokens:
            LLM_TOKENS.labels(provider=provider_name, direction="completion").inc(
                result.completion_tokens
            )

    async def _finalize(
        self,
        result: ChatResult,
        *,
        provider_name: str,
        fallback: str,
        on_usage: RecordUsage | None = None,
        agent: str = "",
    ) -> str:
        self._record_token_metrics(provider_name, result)
        if on_usage and agent and (result.prompt_tokens or result.completion_tokens):
            await on_usage(
                LLMUsageEntry(
                    agent=agent,
                    prompt_tokens=result.prompt_tokens,
                    completion_tokens=result.completion_tokens,
                    total_tokens=result.total_tokens,
                    model=result.model,
                )
            )
        return result.text or fallback

    async def chat(
        self,
        system_prompt: str,
        user_prompt: str,
        fallback: str,
        *,
        role: str = "default",
        agent: str = "",
        on_usage: RecordUsage | None = None,
        model: str | None = None,
    ) -> str:
        if not self._provider:
            logger.debug("LLM unavailable, using fallback response")
            LLM_REQUESTS.labels(provider=self.provider_name, result="fallback").inc()
            return fallback

        params = llm_params_for_role(role)
        try:
            result = await self._provider.chat(
                system_prompt,
                user_prompt,
                max_tokens=int(params["max_tokens"]),
                temperature=float(params["temperature"]),
                model=model,
            )
            LLM_REQUESTS.labels(provider=self._provider.name, result="ok").inc()
            return await self._finalize(
                result,
                provider_name=self._provider.name,
                fallback=fallback,
                on_usage=on_usage,
                agent=agent,
            )
        except asyncio.TimeoutError:
            logger.warning("LLM call timed out after %ss", settings.llm_timeout_seconds)
            LLM_REQUESTS.labels(provider=self._provider.name, result="timeout").inc()
            return fallback
        except Exception as exc:
            logger.warning("LLM call failed (%s): %s", self._provider.name, exc)
            LLM_REQUESTS.labels(provider=self._provider.name, result="error").inc()
            return fallback

    async def chat_json(
        self,
        system_prompt: str,
        user_prompt: str,
        fallback: str,
        *,
        role: str = "default",
        agent: str = "",
        on_usage: RecordUsage | None = None,
        model: str | None = None,
    ) -> str:
        if not self._provider:
            logger.debug("LLM unavailable, using fallback JSON plan")
            LLM_REQUESTS.labels(provider=self.provider_name, result="fallback").inc()
            return fallback

        params = llm_params_for_role(role)
        json_system = (
            f"{system_prompt}\n\n"
            "Respond with a single valid JSON object only. No markdown fences or commentary."
        )
        try:
            result = await self._provider.chat_json(
                json_system,
                user_prompt,
                max_tokens=int(params["max_tokens"]),
                temperature=float(params["temperature"]),
                model=model,
            )
            LLM_REQUESTS.labels(provider=self._provider.name, result="ok").inc()
            return await self._finalize(
                result,
                provider_name=self._provider.name,
                fallback=fallback,
                on_usage=on_usage,
                agent=agent,
            )
        except asyncio.TimeoutError:
            logger.warning("LLM JSON call timed out after %ss", settings.llm_timeout_seconds)
            LLM_REQUESTS.labels(provider=self._provider.name, result="timeout").inc()
            return fallback
        except Exception as exc:
            logger.warning("LLM JSON call failed (%s): %s", self._provider.name, exc)
            LLM_REQUESTS.labels(provider=self._provider.name, result="error").inc()
            return fallback

    async def chat_stream(
        self,
        system_prompt: str,
        user_prompt: str,
        fallback: str,
        *,
        role: str = "default",
        agent: str = "",
        on_usage: RecordUsage | None = None,
        model: str | None = None,
    ):
        if not self._provider:
            LLM_REQUESTS.labels(provider=self.provider_name, result="fallback").inc()
            if fallback:
                yield fallback
            return

        params = llm_params_for_role(role)
        try:
            stream_iter, usage_holder = await self._provider.chat_stream_with_usage(
                system_prompt,
                user_prompt,
                max_tokens=int(params["max_tokens"]),
                temperature=float(params["temperature"]),
                model=model,
            )
            async for chunk in stream_iter:
                if chunk:
                    yield chunk
            usage_result = usage_holder.get("usage") if isinstance(usage_holder, dict) else usage_holder
            if usage_result:
                await self._finalize(
                    usage_result,
                    provider_name=self._provider.name,
                    fallback=fallback,
                    on_usage=on_usage,
                    agent=agent,
                )
            LLM_REQUESTS.labels(provider=self._provider.name, result="ok").inc()
        except asyncio.TimeoutError:
            logger.warning("LLM stream timed out after %ss", settings.llm_timeout_seconds)
            LLM_REQUESTS.labels(provider=self._provider.name, result="timeout").inc()
            if fallback:
                yield fallback
        except Exception as exc:
            logger.warning("LLM stream failed (%s): %s", self._provider.name, exc)
            LLM_REQUESTS.labels(provider=self._provider.name, result="error").inc()
            if fallback:
                yield fallback
