"""Route assignments to in-process agents or distributed worker streams."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from backend.config import settings
from backend.constants import PLANNER
from backend.core.worker_stream import WorkerStreamHub, envelope_from_assignment
from backend.models.message import MessageIntent, MessageType
from backend.models.plan import TaskAssignment, TaskPlan
from backend.models.task_context import TaskContext

if TYPE_CHECKING:
    from backend.agents.planner import PlannerAgent

logger = logging.getLogger(__name__)


class WorkerDispatcher:
    def __init__(
        self,
        hub: WorkerStreamHub | None,
        remote_agents: set[str],
    ) -> None:
        self._hub = hub
        self._remote_agents = remote_agents

    def is_remote(self, agent_name: str) -> bool:
        if not settings.distributed_workers or not self._hub:
            return False
        if agent_name == PLANNER:
            return False
        return agent_name in self._remote_agents

    async def send_assignment(
        self,
        planner: PlannerAgent,
        assignment: TaskAssignment,
        plan: TaskPlan,
        ctx: TaskContext,
        task_text: str,
    ) -> None:
        metadata = {
            "intent": MessageIntent.ASSIGNMENT_START.value,
            "assignment_id": assignment.id,
            "attempt": assignment.attempt,
        }
        if self.is_remote(assignment.agent):
            assert self._hub is not None
            envelope = envelope_from_assignment(
                task_id=planner._current_task_id,
                assignment_id=assignment.id,
                agent=assignment.agent,
                payload=task_text,
                attempt=assignment.attempt,
                metadata=metadata,
            )
            await self._hub.publish_task(envelope)
            logger.info(
                "Dispatched %s assignment %s to worker stream",
                assignment.agent,
                assignment.id,
            )
            return

        await planner.send(
            assignment.agent,
            task_text,
            message_type=MessageType.TASK,
            metadata=metadata,
        )
