"""In-memory LLM streaming buffers for live task UI updates."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class StreamState:
    assignment_id: str = ""
    agent: str = ""
    text: str = ""
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class StreamBuffer:
    def __init__(self) -> None:
        self._states: dict[str, StreamState] = {}
        self._lock = asyncio.Lock()

    async def append(
        self,
        task_id: str,
        *,
        assignment_id: str,
        agent: str,
        chunk: str,
    ) -> None:
        if not task_id or not chunk:
            return
        async with self._lock:
            state = self._states.setdefault(task_id, StreamState())
            state.assignment_id = assignment_id or state.assignment_id
            state.agent = agent or state.agent
            state.text += chunk
            state.updated_at = datetime.now(timezone.utc)

    async def finish(self, task_id: str) -> None:
        async with self._lock:
            self._states.pop(task_id, None)

    async def snapshot(self, task_id: str) -> dict[str, str]:
        async with self._lock:
            state = self._states.get(task_id)
            if not state or not state.text:
                return {}
            return {
                "streaming_assignment": state.assignment_id,
                "streaming_agent": state.agent,
                "partial_result": state.text,
            }
