"""Agent protocol — platform depends on this interface, not concrete implementations."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from backend.models.message import Message


@runtime_checkable
class AgentProtocol(Protocol):
    name: str
    role: str
    capabilities: list[str]
    description: str
    memory: dict[str, Any]

    async def register(self) -> None: ...
    async def start(self) -> None: ...
    async def stop(self) -> None: ...

    async def send(self, to_agent: str, content: str, **kwargs: Any) -> Message: ...
