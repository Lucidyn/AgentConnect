"""LLM client — delegates to configured provider with rule-based fallback."""

from __future__ import annotations

import logging
import time

from backend.config import settings
from backend.core.llm_providers import create_provider
from backend.core.metrics import LLM_REQUESTS

logger = logging.getLogger(__name__)


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

    async def chat(
        self,
        system_prompt: str,
        user_prompt: str,
        fallback: str,
    ) -> str:
        if not self._provider:
            logger.debug("LLM unavailable, using fallback response")
            LLM_REQUESTS.labels(provider=self.provider_name, result="fallback").inc()
            return fallback

        try:
            result = await self._provider.chat(system_prompt, user_prompt)
            LLM_REQUESTS.labels(provider=self._provider.name, result="ok").inc()
            return result or fallback
        except Exception as exc:
            logger.warning("LLM call failed (%s): %s", self._provider.name, exc)
            LLM_REQUESTS.labels(provider=self._provider.name, result="error").inc()
            return fallback
