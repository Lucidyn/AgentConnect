"""Planner Agent — per-task context and scheduling (multi-task safe)."""

from __future__ import annotations

import json
import logging
import re
from uuid import uuid4

from backend.config import settings
from backend.constants import CODER, PLANNER, REVIEWER
from backend.core.agent import Agent
from backend.core.plan_dispatch import build_assignment_task
from backend.models.artifact import Artifact
from backend.models.message import Message, MessageIntent, MessageType
from backend.models.plan import AssignmentStatus, TaskAssignment, TaskPlan
from backend.models.task import TaskStatus
from backend.models.task_context import LoopState, TaskContext

logger = logging.getLogger(__name__)

_VISION_KEYWORDS = ("image", "ocr", "vision", "图片", "识别", "检测", "paddle", "yolo")


def _build_system_prompt(agent_catalog: str) -> str:
    return f"""你是 Planner Agent，负责将用户任务动态拆解并调度合适的 Agent。

当前可用 Agent（通过 Registry 发现）：
{agent_catalog}

根据任务内容选择最合适的 Agent，支持并行和依赖关系。

回复格式（JSON）：
{{
  "summary": "计划概述",
  "steps": ["步骤1", "步骤2"],
  "assignments": [
    {{"id": "t1", "agent": "Research", "task": "具体任务", "depends_on": []}},
    {{"id": "t2", "agent": "Vision", "task": "具体任务", "depends_on": []}},
    {{"id": "t3", "agent": "Coder", "task": "具体任务", "depends_on": ["t1", "t2"]}}
  ]
}}

规则：
- agent 名称必须来自可用 Agent 列表
- depends_on 引用其他 assignment 的 id
- 无依赖的任务可并行执行
- 只输出 JSON"""


class PlannerAgent(Agent):
    name = "Planner"
    role = "planner"
    capabilities = ["planning", "task_decomposition", "orchestration", "scheduling"]
    description = "动态拆解用户任务，智能调度专业 Agent"

    async def think(self, message: Message) -> str | None:
        if not self._current_task_id:
            logger.warning("Planner received message without task_id")
            return None
        if message.message_type == MessageType.STATUS:
            action = message.metadata.get("approval_action")
            if action:
                return await self._handle_approval(action, message.metadata)
        if message.from_agent == "User":
            if message.content.startswith("approval:"):
                return None
            existing = await self._load_plan()
            if existing and not existing.all_done() and not existing.has_failed():
                return await self._resume_plan(existing)
            return await self._start_plan(message.content)
        if message.metadata.get("needs_approval"):
            return await self._request_approval(message)
        if message.metadata.get("needs_retry"):
            return await self._on_retry_request(message)
        if message.message_type == MessageType.ERROR:
            return await self._on_agent_failed(message)
        if message.message_type in (MessageType.RESPONSE, MessageType.TASK):
            return await self._on_agent_done(message)
        return None

    async def _load_ctx(self) -> TaskContext:
        if not self.task_store:
            return TaskContext()
        task = await self.task_store.get(self._current_task_id)
        if not task:
            return TaskContext()
        return TaskContext.model_validate(task.context or {})

    async def _save_ctx(self, ctx: TaskContext) -> None:
        if self.task_store:
            await self.task_store.save_context(self._current_task_id, ctx.model_dump())

    async def _load_plan(self) -> TaskPlan | None:
        if not self.task_store:
            return None
        task = await self.task_store.get(self._current_task_id)
        return TaskContext.plan_from_record(task.plan if task else None)

    async def _persist_plan(self, plan: TaskPlan) -> None:
        if self.task_store:
            await self.task_store.save_plan(self._current_task_id, plan.to_context())

    async def _start_plan(self, user_task: str) -> str:
        if self.task_store:
            await self.task_store.update_status(self._current_task_id, TaskStatus.PLANNING)

        plan = await self._build_plan(user_task)
        dispatched = await self._dispatch_ready(plan, await self._load_ctx())

        await self._persist_plan(plan)

        return (
            f"计划已生成：{plan.summary}\n"
            f"共 {len(plan.assignments)} 个子任务，已调度 {dispatched} 个。"
        )

    async def _resume_plan(self, plan: TaskPlan) -> str:
        if self.task_store:
            await self.task_store.update_status(self._current_task_id, TaskStatus.RUNNING)

        ctx = await self._load_ctx()
        plan.reset_running_to_pending()
        dispatched = await self._dispatch_ready(plan, ctx)
        await self._persist_plan(plan)

        return (
            f"任务已恢复：{plan.summary}\n"
            f"已重新调度 {dispatched} 个子任务。"
        )

    async def _fail_task(self, error: str) -> None:
        if self.task_store:
            await self.task_store.mark_failed(self._current_task_id, error)
        if self.services.on_task_finished:
            await self.services.on_task_finished(self._current_task_id)

    async def _on_agent_failed(self, message: Message) -> str | None:
        plan = await self._load_plan()
        if not plan:
            await self._fail_task(message.content)
            return None

        assignment_id = message.metadata.get("assignment_id", "")
        assignment = plan.find_assignment(
            assignment_id=assignment_id, agent_name=message.from_agent
        )
        if not assignment:
            await self._fail_task(f"Agent error (unknown assignment): {message.content}")
            return None
        if self._is_stale_attempt(message, assignment):
            return None

        if assignment.status not in (AssignmentStatus.RUNNING, AssignmentStatus.PENDING):
            return None

        ctx = await self._load_ctx()
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
            await self._save_ctx(ctx)
            await self._persist_plan(plan)
            await self._dispatch_ready(plan, ctx)
            await self._persist_plan(plan)
            return None

        assignment.status = AssignmentStatus.FAILED
        await self._persist_plan(plan)
        await self._fail_task(
            f"子任务 {assignment.id} ({assignment.agent}) 失败：{message.content}"
        )
        return None

    async def _on_retry_request(self, message: Message) -> str | None:
        """Reviewer (or other agent) requests re-running an upstream assignment."""
        plan = await self._load_plan()
        if not plan:
            return None

        reviewer_id = message.metadata.get("assignment_id", "")
        reviewer_asg = plan.find_assignment(assignment_id=reviewer_id)
        if not reviewer_asg:
            reviewer_asg = plan.find_assignment(agent_name=message.from_agent)
        if reviewer_asg and self._is_stale_attempt(message, reviewer_asg):
            return None

        ctx = await self._load_ctx()

        coder_asg = self._find_upstream_coder(plan, reviewer_asg)
        if not coder_asg:
            logger.warning("Retry requested but no Coder assignment found in plan")
            return None

        loop = ctx.loops.get(
            coder_asg.id,
            LoopState(max_iterations=settings.loop_max_iterations),
        )
        loop.max_iterations = loop.max_iterations or settings.loop_max_iterations
        loop.feedback = message.content
        loop.iteration += 1
        ctx.loops[coder_asg.id] = loop
        ctx.retry_feedback = message.content

        if loop.iteration > loop.max_iterations:
            loop.status = "failed"
            ctx.approval_message = (
                f"Loop exceeded {loop.max_iterations} iteration(s) for "
                f"{coder_asg.id} ({coder_asg.agent}).\n\n{message.content}"
            )
            ctx.approval_assignment_id = reviewer_asg.id if reviewer_asg else ""
            await self._save_ctx(ctx)
            if self.task_store:
                await self.task_store.update_status(
                    self._current_task_id, TaskStatus.WAITING_APPROVAL
                )
            logger.warning(
                "Loop for assignment %s exceeded max iterations (%d)",
                coder_asg.id,
                loop.max_iterations,
            )
            return None

        loop.status = "running"
        reset_ids = plan.reset_to_pending(coder_asg.id)
        for reset_id in reset_ids:
            ctx.results.pop(reset_id, None)
        await self._save_ctx(ctx)

        if self.task_store:
            await self.task_store.update_status(self._current_task_id, TaskStatus.RUNNING)

        await self._persist_plan(plan)
        await self._dispatch_ready(plan, ctx)
        await self._persist_plan(plan)
        return None

    @staticmethod
    def _find_upstream_coder(
        plan: TaskPlan, from_assignment: TaskAssignment | None
    ) -> TaskAssignment | None:
        if from_assignment:
            for dep_id in reversed(from_assignment.depends_on):
                dep = plan.find_assignment(assignment_id=dep_id)
                if dep and dep.agent == CODER:
                    return dep
        for assignment in reversed(plan.assignments):
            if assignment.agent == CODER:
                return assignment
        return None

    async def _request_approval(self, message: Message) -> str | None:
        ctx = await self._load_ctx()
        ctx.approval_message = message.content
        ctx.approval_assignment_id = message.metadata.get("assignment_id", "")
        await self._save_ctx(ctx)
        if self.task_store:
            await self.task_store.update_status(
                self._current_task_id, TaskStatus.WAITING_APPROVAL
            )
        logger.info("Task %s waiting for human approval", self._current_task_id)
        return None

    async def _handle_approval(self, action: str, metadata: dict) -> str | None:
        plan = await self._load_plan()
        if not plan:
            return None

        ctx = await self._load_ctx()
        assignment_id = metadata.get("assignment_id") or ctx.approval_assignment_id

        if action == "reject":
            if self.task_store:
                await self.task_store.mark_failed(
                    self._current_task_id, "Rejected by human reviewer"
                )
            if self.services.on_task_finished:
                await self.services.on_task_finished(self._current_task_id)
            return None

        if action == "retry":
            if self.task_store:
                await self.task_store.update_status(self._current_task_id, TaskStatus.RUNNING)
            coder = self.registry.get("Coder")
            if coder:
                await self.send(
                    coder.name,
                    f"人工要求修改：\n{ctx.approval_message}",
                    message_type=MessageType.TASK,
                    metadata={"assignment_id": assignment_id},
                )
            ctx.approval_message = ""
            await self._save_ctx(ctx)
            return None

        # approve — mark review step done and continue
        if assignment_id:
            plan.mark_done(assignment_id=assignment_id)
        else:
            plan.mark_done(agent_name="Reviewer")
        ctx.approval_message = ""
        ctx.approval_assignment_id = ""
        await self._save_ctx(ctx)
        if self.task_store:
            await self.task_store.update_status(self._current_task_id, TaskStatus.RUNNING)

        if plan.all_done():
            final = f"人工审批通过，任务完成。\n{ctx.coder_result or ''}"
            if self.task_store:
                await self.task_store.save_result(self._current_task_id, final)
            if self.services.on_task_finished:
                await self.services.on_task_finished(self._current_task_id)
            return None

        await self._persist_plan(plan)
        await self._dispatch_ready(plan, ctx)
        await self._persist_plan(plan)
        return None

    async def _on_agent_done(self, message: Message) -> str | None:
        plan = await self._load_plan()
        if not plan:
            return None

        assignment_id = message.metadata.get("assignment_id", "")
        assignment = plan.find_assignment(
            assignment_id=assignment_id, agent_name=message.from_agent
        )
        if not assignment:
            return None
        if self._is_stale_attempt(message, assignment):
            return None
        assignment = plan.mark_done(
            assignment_id=assignment.id, agent_name=message.from_agent
        )
        if not assignment:
            return None

        logger.info(
            "[%s] task=%s completed %s", message.from_agent, self._current_task_id, assignment.id
        )

        ctx = await self._load_ctx()
        ctx.results[assignment.id] = message.content
        if self.task_store:
            artifact = await self.task_store.save_artifact(
                Artifact(
                    task_id=self._current_task_id,
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
        if assignment.agent == "Research":
            ctx.research_result = message.content
            ctx.workspace.facts.append(message.content[:500])
        elif assignment.agent == CODER:
            ctx.coder_result = message.content
            ctx.retry_feedback = ""
            loop = ctx.loops.get(assignment.id)
            if loop:
                loop.status = "passed"
                ctx.loops[assignment.id] = loop
        elif assignment.agent == "Vision":
            ctx.vision_result = message.content
        elif assignment.agent == "TestRunner" and "FAILED" in message.content:
            ctx.workspace.blockers.append(message.content)
        await self._save_ctx(ctx)

        if plan.all_done():
            final = f"所有任务完成！\n{message.content}"
            if self.task_store:
                await self.task_store.save_result(self._current_task_id, final)
                await self.task_store.save_plan(self._current_task_id, plan.to_context())
            if self.services.on_task_finished:
                await self.services.on_task_finished(self._current_task_id)
            return None

        await self._redispatch_running_dependents(plan, ctx, assignment.id)
        await self._persist_plan(plan)
        await self._dispatch_ready(plan, ctx)
        await self._persist_plan(plan)
        return None

    async def _redispatch_running_dependents(
        self, plan: TaskPlan, ctx: TaskContext, completed_id: str
    ) -> None:
        """Re-send to RUNNING assignments whose dependencies just completed (retry path)."""
        done_ids = {a.id for a in plan.assignments if a.status == AssignmentStatus.DONE}
        for assignment in plan.assignments:
            if assignment.status != AssignmentStatus.RUNNING:
                continue
            if completed_id not in assignment.depends_on:
                continue
            if not all(dep in done_ids for dep in assignment.depends_on):
                continue
            task = build_assignment_task(assignment, plan, ctx)
            assignment.attempt += 1
            await self.send(
                assignment.agent,
                task,
                message_type=MessageType.TASK,
                metadata={
                    "intent": MessageIntent.ASSIGNMENT_START.value,
                    "assignment_id": assignment.id,
                    "attempt": assignment.attempt,
                },
            )

    async def _dispatch_ready(self, plan: TaskPlan, ctx: TaskContext) -> int:
        count = 0
        for assignment in plan.pending_ready():
            task = build_assignment_task(assignment, plan, ctx)
            assignment.status = AssignmentStatus.RUNNING
            assignment.attempt += 1
            await self.send(
                assignment.agent,
                task,
                message_type=MessageType.TASK,
                metadata={
                    "intent": MessageIntent.ASSIGNMENT_START.value,
                    "assignment_id": assignment.id,
                    "attempt": assignment.attempt,
                },
            )
            count += 1
        return count

    @staticmethod
    def _is_stale_attempt(message: Message, assignment: TaskAssignment) -> bool:
        if "attempt" not in message.metadata:
            return False
        try:
            attempt = int(message.metadata.get("attempt", 0))
        except (TypeError, ValueError):
            return True
        return attempt != assignment.attempt

    async def _build_plan(self, user_task: str) -> TaskPlan:
        catalog = self.registry.catalog_for_planner()
        discovered = self.registry.discover(user_task, limit=3)
        discovery_hint = ""
        if discovered:
            names = ", ".join(f"{a.name}({score:.0f})" for a, score in discovered)
            discovery_hint = f"\n推荐 Agent：{names}"

        fallback = self._fallback_plan(user_task)
        raw = await self.llm.chat(
            _build_system_prompt(catalog),
            f"用户任务：{user_task}{discovery_hint}",
            json.dumps(fallback, ensure_ascii=False),
        )
        return self._parse_plan(raw, user_task, fallback)

    def _needs_vision(self, task: str) -> bool:
        lower = task.lower()
        return any(k in lower for k in _VISION_KEYWORDS) and bool(self.registry.get("Vision"))

    def _fallback_plan(self, task: str) -> dict:
        research = self.registry.best_for_task("research documentation")
        coder = self.registry.best_for_task("coding python")
        reviewer = self.registry.best_for_task("code review")
        tester = self.registry.best_for_task("testing validation")
        vision = self.registry.get("Vision")

        research_name = research.name if research else "Research"
        coder_name = coder.name if coder else "Coder"
        reviewer_name = reviewer.name if reviewer else "Reviewer"
        tester_name = tester.name if tester else ""

        if vision and self._needs_vision(task):
            plan = {
                "summary": f"将「{task}」拆解为并行调研+视觉分析→编码→审查",
                "steps": ["并行调研与视觉", "编码", "审查"],
                "assignments": [
                    {
                        "id": "t1",
                        "agent": research_name,
                        "task": f"调研：{task}",
                        "depends_on": [],
                        "reason": "收集实现前需要的技术资料",
                    },
                    {
                        "id": "t2",
                        "agent": vision.name,
                        "task": f"视觉分析：{task}",
                        "depends_on": [],
                        "reason": "任务包含视觉/OCR/检测相关需求",
                    },
                    {
                        "id": "t3",
                        "agent": coder_name,
                        "task": f"实现：{task}",
                        "depends_on": ["t1", "t2"],
                        "reason": "基于调研与视觉结果产出实现",
                    },
                ],
            }
            review_dep = "t3"
            review_id = "t4"
            if tester_name:
                plan["summary"] = f"将「{task}」拆解为并行调研+视觉分析→编码→测试→审查"
                plan["steps"] = ["并行调研与视觉", "编码", "测试", "审查"]
                plan["assignments"].append(
                    {
                        "id": "t4",
                        "agent": tester_name,
                        "task": f"测试：{task}",
                        "depends_on": ["t3"],
                        "reason": "在审查前验证实现是否满足基本质量门槛",
                    }
                )
                review_dep = "t4"
                review_id = "t5"
            plan["assignments"].append(
                {
                    "id": review_id,
                    "agent": reviewer_name,
                    "task": f"审查：{task}",
                    "depends_on": [review_dep],
                    "reason": "最终质量与安全审查",
                }
            )
            return plan

        plan = {
            "summary": f"将「{task}」拆解为调研→编码→审查",
            "steps": ["调研", "编码", "审查"],
            "assignments": [
                {
                    "id": "t1",
                    "agent": research_name,
                    "task": f"调研：{task}",
                    "depends_on": [],
                    "reason": "收集实现前需要的资料",
                },
                {
                    "id": "t2",
                    "agent": coder_name,
                    "task": f"实现：{task}",
                    "depends_on": ["t1"],
                    "reason": "基于调研结果产出实现",
                },
            ],
        }
        review_dep = "t2"
        review_id = "t3"
        if tester_name:
            plan["summary"] = f"将「{task}」拆解为调研→编码→测试→审查"
            plan["steps"] = ["调研", "编码", "测试", "审查"]
            plan["assignments"].append(
                {
                    "id": "t3",
                    "agent": tester_name,
                    "task": f"测试：{task}",
                    "depends_on": ["t2"],
                    "reason": "先用测试结果验证实现",
                }
            )
            review_dep = "t3"
            review_id = "t4"
        plan["assignments"].append(
            {
                "id": review_id,
                "agent": reviewer_name,
                "task": f"审查：{task}",
                "depends_on": [review_dep],
                "reason": "最终质量与安全审查",
            }
        )
        return plan

    def _parse_plan(self, raw: str, task: str, fallback: dict) -> TaskPlan:
        try:
            match = re.search(r"\{.*\}", raw, re.DOTALL)
            data = json.loads(match.group()) if match else fallback
        except (json.JSONDecodeError, AttributeError):
            data = fallback

        assignments = []
        for item in data.get("assignments", []):
            agent_name = item.get("agent", "")
            if not self.registry.get(agent_name):
                discovered = self.registry.best_for_task(item.get("task", task))
                agent_name = discovered.name if discovered else agent_name

            assignments.append(
                TaskAssignment(
                    id=item.get("id", str(uuid4())[:8]),
                    agent=agent_name,
                    task=item.get("task", task),
                    depends_on=item.get("depends_on", []),
                    reason=item.get("reason", ""),
                )
            )

        if not assignments:
            fb = self._fallback_plan(task)
            assignments = [TaskAssignment.model_validate(a) for a in fb["assignments"]]
            data = fb

        plan = TaskPlan(
            summary=data.get("summary", ""),
            steps=data.get("steps", []),
            assignments=assignments,
        )
        errors = plan.validate()
        if errors:
            logger.warning("Invalid plan from LLM (%s), using fallback", "; ".join(errors))
            fb = self._fallback_plan(task)
            return TaskPlan(
                summary=fb.get("summary", ""),
                steps=fb.get("steps", []),
                assignments=[TaskAssignment.model_validate(a) for a in fb["assignments"]],
            )
        return plan
