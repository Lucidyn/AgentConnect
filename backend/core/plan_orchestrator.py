"""Plan execution orchestration — dispatch, retries, completion, and approval."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from backend.config import settings
from backend.constants import GATE_AGENTS, PLANNER, REVIEWER
from backend.core.blackboard import post_entry, record_negotiation
from backend.core.negotiation import run_negotiation_round
from backend.core.plan_dispatch import build_assignment_task
from backend.models.artifact import Artifact
from backend.models.message import Message, MessageIntent, MessageType
from backend.models.plan import AssignmentStatus, TaskAssignment, TaskPlan
from backend.models.task import TaskStatus
from backend.models.task_context import LoopState, TaskContext

if TYPE_CHECKING:
    from backend.agents.planner import PlannerAgent

logger = logging.getLogger(__name__)


def is_stale_attempt(message: Message, assignment: TaskAssignment) -> bool:
    if "attempt" not in message.metadata:
        return False
    try:
        attempt = int(message.metadata.get("attempt", 0))
    except (TypeError, ValueError):
        return True
    return attempt != assignment.attempt


class PlanOrchestrator:
    """Handles assignment lifecycle; PlannerAgent delegates orchestration here."""

    def __init__(self, planner: PlannerAgent) -> None:
        self._planner = planner

    @property
    def task_id(self) -> str:
        return self._planner._current_task_id

    @property
    def task_store(self):
        return self._planner.task_store

    @property
    def services(self):
        return self._planner.services

    async def load_ctx(self) -> TaskContext:
        return await self._planner._load_ctx()

    async def save_ctx(self, ctx: TaskContext) -> None:
        await self._planner._save_ctx(ctx)

    async def load_plan(self) -> TaskPlan | None:
        return await self._planner._load_plan()

    async def persist_plan(self, plan: TaskPlan) -> None:
        await self._planner._persist_plan(plan)

    async def persist_and_dispatch(self, plan: TaskPlan, ctx: TaskContext) -> int:
        await self.persist_plan(plan)
        dispatched = await self.dispatch_ready(plan, ctx)
        await self.persist_plan(plan)
        return dispatched

    async def send_assignment(
        self,
        assignment: TaskAssignment,
        plan: TaskPlan,
        ctx: TaskContext,
        *,
        mark_running: bool = False,
        increment_attempt: bool = True,
    ) -> None:
        if mark_running:
            assignment.status = AssignmentStatus.RUNNING
        if increment_attempt:
            assignment.attempt += 1
        task = build_assignment_task(assignment, plan, ctx)
        await self._planner.send(
            assignment.agent,
            task,
            message_type=MessageType.TASK,
            metadata={
                "intent": MessageIntent.ASSIGNMENT_START.value,
                "assignment_id": assignment.id,
                "attempt": assignment.attempt,
            },
        )

    async def dispatch_ready(self, plan: TaskPlan, ctx: TaskContext) -> int:
        count = 0
        for assignment in plan.pending_ready():
            await self.send_assignment(assignment, plan, ctx, mark_running=True)
            count += 1
        return count

    async def redispatch_running_dependents(
        self, plan: TaskPlan, ctx: TaskContext, completed_id: str
    ) -> None:
        """Re-send to RUNNING assignments whose dependencies just completed."""
        done_ids = {a.id for a in plan.assignments if a.status == AssignmentStatus.DONE}
        for assignment in plan.assignments:
            if assignment.status != AssignmentStatus.RUNNING:
                continue
            if completed_id not in assignment.depends_on:
                continue
            if not all(dep in done_ids for dep in assignment.depends_on):
                continue
            await self.send_assignment(assignment, plan, ctx)

    async def on_agent_failed(self, message: Message) -> None:
        plan = await self.load_plan()
        if not plan:
            await self._planner._fail_task(message.content)
            return

        assignment_id = message.metadata.get("assignment_id", "")
        assignment = plan.find_assignment(
            assignment_id=assignment_id, agent_name=message.from_agent
        )
        if not assignment:
            await self._planner._fail_task(f"Agent error (unknown assignment): {message.content}")
            return
        if is_stale_attempt(message, assignment):
            return
        if assignment.status not in (AssignmentStatus.RUNNING, AssignmentStatus.PENDING):
            return

        ctx = await self.load_ctx()
        retries = ctx.assignment_retries.get(assignment.id, 0)
        max_retries = settings.assignment_max_retries

        logger.warning(
            "[%s] assignment %s failed (retry %d/%d): %s",
            message.from_agent,
            assignment.id,
            retries,
            max_retries,
            message.content[:200],
        )

        if retries < max_retries:
            ctx.assignment_retries[assignment.id] = retries + 1
            assignment.status = AssignmentStatus.PENDING
            await self.save_ctx(ctx)
            await self.persist_and_dispatch(plan, ctx)
            return

        assignment.status = AssignmentStatus.FAILED
        await self.persist_plan(plan)
        await self._planner._fail_task(
            f"子任务 {assignment.id} ({assignment.agent}) 失败：{message.content}"
        )

    async def on_retry_request(self, message: Message) -> None:
        await self._quality_retry(
            feedback=message.content,
            from_assignment_id=message.metadata.get("assignment_id", ""),
            from_agent=message.from_agent,
            attempt_message=message,
        )

    async def on_human_retry(self, assignment_id: str, feedback: str) -> None:
        await self._quality_retry(
            feedback=f"人工要求修改：\n{feedback}",
            from_assignment_id=assignment_id,
            from_agent="User",
            attempt_message=None,
        )

    async def _quality_retry(
        self,
        *,
        feedback: str,
        from_assignment_id: str,
        from_agent: str,
        attempt_message: Message | None,
    ) -> None:
        plan = await self.load_plan()
        if not plan:
            return

        source_asg = plan.find_assignment(assignment_id=from_assignment_id)
        if not source_asg:
            source_asg = plan.find_assignment(agent_name=from_agent)
        if source_asg and attempt_message and is_stale_attempt(attempt_message, source_asg):
            return

        ctx = await self.load_ctx()
        producer_asg = self._find_upstream_producer(plan, source_asg)
        if not producer_asg:
            logger.warning("Retry requested but no producer assignment found in plan")
            return

        loop = ctx.loops.get(
            producer_asg.id,
            LoopState(max_iterations=settings.loop_max_iterations),
        )
        loop.max_iterations = loop.max_iterations or settings.loop_max_iterations
        loop.feedback = feedback
        loop.iteration += 1
        ctx.loops[producer_asg.id] = loop
        ctx.retry_feedback = feedback

        if loop.iteration > loop.max_iterations:
            loop.status = "failed"
            ctx.approval_message = (
                f"Loop exceeded {loop.max_iterations} iteration(s) for "
                f"{producer_asg.id} ({producer_asg.agent}).\n\n{feedback}"
            )
            ctx.approval_assignment_id = source_asg.id if source_asg else ""
            await self.save_ctx(ctx)
            if self.task_store:
                await self.task_store.update_status(self.task_id, TaskStatus.WAITING_APPROVAL)
            logger.warning(
                "Loop for assignment %s exceeded max iterations (%d)",
                producer_asg.id,
                loop.max_iterations,
            )
            return

        loop.status = "running"
        reset_ids = plan.reset_to_pending(producer_asg.id)
        for reset_id in reset_ids:
            ctx.results.pop(reset_id, None)
        await self.save_ctx(ctx)

        if self.task_store:
            await self.task_store.update_status(self.task_id, TaskStatus.RUNNING)

        await self.persist_and_dispatch(plan, ctx)

    async def on_request_approval(self, message: Message) -> None:
        ctx = await self.load_ctx()
        ctx.approval_message = message.content
        ctx.approval_assignment_id = message.metadata.get("assignment_id", "")
        await self.save_ctx(ctx)
        if self.task_store:
            await self.task_store.update_status(self.task_id, TaskStatus.WAITING_APPROVAL)
        logger.info("Task %s waiting for human approval", self.task_id)

    async def on_handle_approval(self, action: str, metadata: dict) -> None:
        plan = await self.load_plan()
        if not plan:
            return

        ctx = await self.load_ctx()
        assignment_id = metadata.get("assignment_id") or ctx.approval_assignment_id

        if action == "reject":
            if self.task_store:
                await self.task_store.mark_failed(self.task_id, "Rejected by human reviewer")
            if self.services.on_task_finished:
                await self.services.on_task_finished(self.task_id)
            return

        if action == "retry":
            feedback = ctx.approval_message
            ctx.approval_message = ""
            await self.save_ctx(ctx)
            if self.task_store:
                await self.task_store.update_status(self.task_id, TaskStatus.RUNNING)
            await self.on_human_retry(assignment_id, feedback)
            return

        if assignment_id:
            plan.mark_done(assignment_id=assignment_id)
        else:
            plan.mark_done(agent_name=REVIEWER)
        ctx.approval_message = ""
        ctx.approval_assignment_id = ""
        await self.save_ctx(ctx)
        if self.task_store:
            await self.task_store.update_status(self.task_id, TaskStatus.RUNNING)

        if plan.all_done():
            final = f"人工审批通过，任务完成。\n{ctx.primary_output(plan)}"
            if self.task_store:
                await self.task_store.save_result(self.task_id, final)
            if self.services.on_task_finished:
                await self.services.on_task_finished(self.task_id)
            return

        await self.persist_and_dispatch(plan, ctx)

    async def on_agent_done(self, message: Message) -> None:
        plan = await self.load_plan()
        if not plan:
            return

        assignment_id = message.metadata.get("assignment_id", "")
        assignment = plan.find_assignment(
            assignment_id=assignment_id, agent_name=message.from_agent
        )
        if not assignment:
            return
        if is_stale_attempt(message, assignment):
            return
        assignment = plan.mark_done(
            assignment_id=assignment.id, agent_name=message.from_agent
        )
        if not assignment:
            return

        logger.info(
            "[%s] task=%s completed %s", message.from_agent, self.task_id, assignment.id
        )

        ctx = await self.load_ctx()
        ctx.record_result(assignment, message.content)
        if ctx.collaboration_mode == "blackboard":
            post_entry(
                ctx,
                author=message.from_agent,
                content=message.content[:800],
                entry_type="fact",
                thread_id=assignment.id,
            )
            for question in _extract_questions(message.content):
                post_entry(
                    ctx,
                    author=message.from_agent,
                    content=question,
                    entry_type="question",
                    thread_id=assignment.id,
                )
                record_negotiation(
                    ctx,
                    f"{message.from_agent} 提出：{question[:120]}",
                )
            await run_negotiation_round(self, plan, ctx, assignment)
        if self.task_store:
            artifact = await self.task_store.save_artifact(
                Artifact(
                    task_id=self.task_id,
                    assignment_id=assignment.id,
                    type=f"{assignment.agent.lower()}_result",
                    content=message.content,
                    metadata={
                        "attempt": assignment.attempt,
                        "message_id": message.id,
                        "reason": assignment.reason,
                    },
                    created_by=message.from_agent,
                )
            )
            ctx.workspace.artifacts.append(artifact.id)
        await self.save_ctx(ctx)

        if plan.all_done():
            final = f"所有任务完成！\n{message.content}"
            if self.task_store:
                await self.task_store.save_result(self.task_id, final)
                await self.task_store.save_plan(self.task_id, plan.to_context())
            if self.services.on_task_finished:
                await self.services.on_task_finished(self.task_id)
            return

        await self.redispatch_running_dependents(plan, ctx, assignment.id)
        await self.persist_and_dispatch(plan, ctx)

    @staticmethod
    def _find_upstream_producer(
        plan: TaskPlan, from_assignment: TaskAssignment | None
    ) -> TaskAssignment | None:
        """Find the main content-producing assignment to reset on quality retry."""
        if from_assignment:
            for dep_id in reversed(from_assignment.depends_on):
                dep = plan.find_assignment(assignment_id=dep_id)
                if dep and dep.agent not in GATE_AGENTS:
                    return dep
        for assignment in reversed(plan.assignments):
            if assignment.agent not in GATE_AGENTS and assignment.agent != PLANNER:
                return assignment
        return None


def _extract_questions(content: str) -> list[str]:
    questions: list[str] = []
    for line in content.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.endswith("?") or stripped.endswith("？"):
            questions.append(stripped[:200])
        elif stripped.startswith("问题") or stripped.lower().startswith("question"):
            questions.append(stripped[:200])
    return questions[:3]
