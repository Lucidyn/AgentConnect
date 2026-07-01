"""Execute assignments on worker agents and capture planner replies."""

from __future__ import annotations

import logging
from typing import Any

from backend.constants import PLANNER
from backend.core.agent import Agent
from backend.core.worker_protocol import WorkerResultEnvelope, WorkerTaskEnvelope
from backend.models.message import Message, MessageIntent, MessageType

logger = logging.getLogger(__name__)


async def execute_assignment(
    agent: Agent, envelope: WorkerTaskEnvelope
) -> WorkerResultEnvelope:
    """Run one assignment on a worker-local agent."""
    message = Message(
        from_agent=PLANNER,
        to_agent=agent.name,
        content=envelope.payload,
        message_type=MessageType.TASK,
        task_id=envelope.task_id,
        trace_id=envelope.trace_id or envelope.task_id,
        metadata={
            **envelope.metadata,
            "intent": MessageIntent.ASSIGNMENT_START.value,
            "assignment_id": envelope.assignment_id,
            "attempt": envelope.attempt,
        },
    ).with_trace()

    captured: dict[str, Any] = {"content": "", "error": False, "meta": {}}
    original_send = agent.send

    async def capture_send(
        to_agent: str,
        content: str,
        message_type: MessageType = MessageType.TASK,
        metadata: dict | None = None,
        task_id: str = "",
    ):
        if to_agent == PLANNER:
            captured["content"] = content
            captured["meta"] = dict(metadata or {})
            if message_type == MessageType.ERROR:
                captured["error"] = True
        return await original_send(
            to_agent,
            content,
            message_type=message_type,
            metadata=metadata,
            task_id=task_id,
        )

    agent._current_task_id = envelope.task_id
    agent.send = capture_send  # type: ignore[method-assign]
    try:
        direct = await agent.think(message)
        content = direct if direct is not None else captured["content"]
        success = bool(content) and not captured["error"]
        if not content and not success:
            content = "Worker produced empty result"
        return WorkerResultEnvelope(
            envelope_id=envelope.envelope_id,
            task_id=envelope.task_id,
            assignment_id=envelope.assignment_id,
            agent=agent.name,
            success=success,
            content=content if success else "",
            error="" if success else content,
            metadata={
                **captured["meta"],
                "attempt": envelope.attempt,
            },
        )
    except Exception as exc:
        logger.exception("[%s] worker assignment failed", agent.name)
        return WorkerResultEnvelope(
            envelope_id=envelope.envelope_id,
            task_id=envelope.task_id,
            assignment_id=envelope.assignment_id,
            agent=agent.name,
            success=False,
            error=str(exc),
            metadata={"attempt": envelope.attempt},
        )
    finally:
        agent.send = original_send  # type: ignore[method-assign]
        agent._current_task_id = ""
