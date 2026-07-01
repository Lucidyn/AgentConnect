"""Planner Agent — per-task context and scheduling (multi-task safe)."""

from __future__ import annotations

import json
import logging
import re
from uuid import uuid4

from backend.config import settings
from backend.core.agent import Agent
from backend.core.fallback_plan import FallbackPlanBuilder
from backend.core.plan_orchestrator import PlanOrchestrator
from backend.core.plan_templates import get_template, plan_from_custom
from backend.core.plan_validate import validate_assignments
from backend.models.message import Message, MessageIntent, MessageType
from backend.models.plan import TaskAssignment, TaskPlan
from backend.models.task import TaskStatus
from backend.models.task_context import TaskContext

logger = logging.getLogger(__name__)


def _build_system_prompt(agent_catalog: str) -> str:
    fast_rules = ""
    if settings.fast_mode:
        fast_rules = """
- 简单 API/CRUD/单文件任务：只用 Coder + Reviewer（跳过 Research、TestRunner）
- 只有明确需要查论文/外部文档时才加 Research
- 只有用户明确要求测试时才加 TestRunner
"""
    return f"""你是 Planner Agent，负责将用户任务动态拆解并调度合适的 Agent。

当前可用 Agent（通过 Registry 发现）：
{agent_catalog}

根据任务类型选择 Agent（不仅限于编码）：
- 编码/实现/API → Coder (+ TestRunner 可选)
- 写作/文案/内容 → Writer
- 分析/对比/报告 → Analyst (+ Research 可选)
- 调研/资料 → Research
- 翻译/本地化 → Translator
- 跨领域混合（调研+分析+写作）→ Research → Analyst → Writer → Reviewer
- 质量把关 → Reviewer

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
- 只输出 JSON，不要解释{fast_rules}"""


class PlannerAgent(Agent):
    name = "Planner"
    role = "planner"
    capabilities = ["planning", "task_decomposition", "orchestration", "scheduling"]
    description = "动态拆解用户任务，智能调度专业 Agent"

    def __init__(self, services) -> None:
        super().__init__(services)
        self._orchestrator = PlanOrchestrator(self)
        self._fallback_builder = FallbackPlanBuilder(self.registry)

    async def think(self, message: Message) -> str | None:
        if not self._current_task_id:
            logger.warning("Planner received message without task_id")
            return None
        if message.message_type == MessageType.STATUS:
            action = message.metadata.get("approval_action")
            if action:
                await self._orchestrator.on_handle_approval(action, message.metadata)
                return None
        if message.from_agent == "User":
            if message.content.startswith("approval:"):
                return None
            existing = await self._load_plan()
            if existing and not existing.all_done() and not existing.has_failed():
                return await self._resume_plan(existing)
            return await self._start_plan(message.content)

        intent = message.metadata.get("intent", "")
        if intent == MessageIntent.APPROVAL_REQUEST.value or message.metadata.get("needs_approval"):
            await self._orchestrator.on_request_approval(message)
            return None
        if intent == MessageIntent.RETRY_REQUEST.value or message.metadata.get("needs_retry"):
            await self._orchestrator.on_retry_request(message)
            return None
        if message.message_type == MessageType.ERROR:
            await self._orchestrator.on_agent_failed(message)
            return None
        if message.message_type in (MessageType.RESPONSE, MessageType.TASK):
            await self._orchestrator.on_agent_done(message)
            return None
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
            await self.task_store.save_context(self._current_task_id, ctx.model_dump(mode="json"))

    async def _load_plan(self) -> TaskPlan | None:
        if not self.task_store:
            return None
        task = await self.task_store.get(self._current_task_id)
        return TaskPlan.from_record(task.plan if task else None)

    async def _persist_plan(self, plan: TaskPlan) -> None:
        if self.task_store:
            await self.task_store.save_plan(self._current_task_id, plan.to_context())

    async def _start_plan(self, user_task: str) -> str:
        if self.task_store:
            await self.task_store.update_status(self._current_task_id, TaskStatus.PLANNING)

        plan = await self._build_plan(user_task)
        ctx = await self._load_ctx()
        dispatched = await self._orchestrator.dispatch_ready(plan, ctx)
        await self._persist_plan(plan)
        if self.task_store:
            await self.task_store.update_status(self._current_task_id, TaskStatus.RUNNING)

        return (
            f"计划已生成：{plan.summary}\n"
            f"共 {len(plan.assignments)} 个子任务，已调度 {dispatched} 个。"
        )

    async def _resume_plan(self, plan: TaskPlan) -> str:
        if self.task_store:
            await self.task_store.update_status(self._current_task_id, TaskStatus.RUNNING)

        ctx = await self._load_ctx()
        plan.reset_running_to_pending()
        dispatched = await self._orchestrator.dispatch_ready(plan, ctx)
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

    async def _build_plan(self, user_task: str) -> TaskPlan:
        ctx = await self._load_ctx()

        if ctx.custom_plan:
            try:
                plan = plan_from_custom(ctx.custom_plan, user_task, self.registry)
                logger.info("Using custom plan with %d assignments", len(plan.assignments))
                return plan
            except ValueError as exc:
                logger.warning("Invalid custom plan, falling back: %s", exc)

        if ctx.template_id:
            template = get_template(ctx.template_id)
            if template:
                if not ctx.collaboration_mode or ctx.collaboration_mode == "planner":
                    ctx.collaboration_mode = template.collaboration_mode
                if not ctx.negotiation:
                    ctx.negotiation = template.negotiation
                await self._save_ctx(ctx)
                plan = template.to_plan(user_task, self.registry)
                logger.info("Using template %s with %d assignments", ctx.template_id, len(plan.assignments))
                return plan
            logger.warning("Unknown template_id=%s, using LLM/fallback", ctx.template_id)

        catalog = self.registry.catalog_for_planner()
        discovered = self.registry.discover(user_task, limit=3)
        discovery_hint = ""
        if discovered:
            names = ", ".join(f"{a.name}({score:.0f})" for a, score in discovered)
            discovery_hint = f"\n推荐 Agent：{names}"

        fallback = self._fallback_builder.build(user_task)
        if settings.fast_mode and settings.fast_skip_planner_llm:
            logger.info("Fast mode: using rule-based plan without Planner LLM")
            return self._parse_plan(json.dumps(fallback, ensure_ascii=False), user_task, fallback)

        raw = await self.llm.chat(
            _build_system_prompt(catalog),
            f"用户任务：{user_task}{discovery_hint}",
            json.dumps(fallback, ensure_ascii=False),
            role="planner",
        )
        return self._parse_plan(raw, user_task, fallback)

    def _fallback_plan(self, task: str) -> dict:
        """Backward-compatible hook for tests."""
        return self._fallback_builder.build(task)

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
            fb = self._fallback_builder.build(task)
            assignments = [TaskAssignment.model_validate(a) for a in fb["assignments"]]
            data = fb

        plan = TaskPlan(
            summary=data.get("summary", ""),
            steps=data.get("steps", []),
            assignments=assignments,
        )
        errors = validate_assignments(plan.assignments)
        if errors:
            logger.warning("Invalid plan from LLM (%s), using fallback", "; ".join(errors))
            fb = self._fallback_builder.build(task)
            return TaskPlan(
                summary=fb.get("summary", ""),
                steps=fb.get("steps", []),
                assignments=[TaskAssignment.model_validate(a) for a in fb["assignments"]],
            )
        return plan
