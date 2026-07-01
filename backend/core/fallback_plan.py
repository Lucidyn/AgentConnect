"""Rule-based fallback plans when LLM output is missing or invalid."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from backend.config import settings
from backend.core.task_domain import TaskDomain, detect_task_domain

if TYPE_CHECKING:
    from backend.core.registry import AgentRegistry

_VISION_KEYWORDS = ("image", "ocr", "vision", "图片", "识别", "检测", "paddle", "yolo")
_SIMPLE_TASK_KEYWORDS = (
    "health",
    "hello",
    "tiny",
    "simple",
    "minimal",
    "demo",
    "crud",
    "小",
    "简单",
)


class FallbackPlanBuilder:
    def __init__(self, registry: AgentRegistry) -> None:
        self._registry = registry

    def build(self, task: str) -> dict[str, Any]:
        domain = detect_task_domain(task)
        research = self._registry.best_for_task("research documentation")
        coder = self._registry.best_for_task("coding python")
        writer = self._registry.get("Writer") or self._registry.best_for_task("writing content")
        analyst = self._registry.get("Analyst") or self._registry.best_for_task("analysis report")
        reviewer = self._registry.best_for_task("code review quality")
        tester = self._registry.best_for_task("testing validation")
        vision = self._registry.get("Vision")

        research_name = research.name if research else "Research"
        coder_name = coder.name if coder else "Coder"
        writer_name = writer.name if writer else "Writer"
        analyst_name = analyst.name if analyst else "Analyst"
        reviewer_name = reviewer.name if reviewer else "Reviewer"
        tester_name = tester.name if tester else ""
        if settings.fast_mode and settings.fast_skip_test_runner:
            tester_name = ""
        skip_research = settings.fast_mode and settings.fast_skip_research

        if domain == TaskDomain.WRITING:
            if settings.fast_mode and self._is_simple_task(task):
                return self._lite_content_pipeline(task, writer_name, reviewer_name)
            return self._writing_pipeline(
                task, research_name, writer_name, reviewer_name, skip_research=skip_research
            )

        if domain in (TaskDomain.ANALYSIS, TaskDomain.RESEARCH):
            return self._analysis_pipeline(
                task, research_name, analyst_name, reviewer_name, skip_research=skip_research
            )

        if domain == TaskDomain.GENERAL:
            return self._general_pipeline(task, reviewer_name)

        if settings.fast_mode and self._is_simple_task(task):
            return self._lite_pipeline(task, coder_name, reviewer_name)

        if vision and self._needs_vision(task):
            return self._vision_pipeline(
                task,
                research_name,
                coder_name,
                reviewer_name,
                tester_name,
                vision.name,
                skip_research=settings.fast_mode and settings.fast_skip_research,
            )
        return self._standard_pipeline(
            task,
            research_name,
            coder_name,
            reviewer_name,
            tester_name,
            skip_research=settings.fast_mode and settings.fast_skip_research,
        )

    @staticmethod
    def _lite_content_pipeline(task: str, writer_name: str, reviewer_name: str) -> dict[str, Any]:
        return {
            "summary": f"快速撰写「{task}」",
            "steps": ["写作", "审查"],
            "assignments": [
                {
                    "id": "t1",
                    "agent": writer_name,
                    "task": f"写作：{task}",
                    "depends_on": [],
                    "reason": "直接产出内容草案",
                },
                {
                    "id": "t2",
                    "agent": reviewer_name,
                    "task": f"审查：{task}",
                    "depends_on": ["t1"],
                    "reason": "检查内容质量与完整性",
                },
            ],
        }

    def _writing_pipeline(
        self,
        task: str,
        research_name: str,
        writer_name: str,
        reviewer_name: str,
        *,
        skip_research: bool = False,
    ) -> dict[str, Any]:
        if skip_research:
            return self._lite_content_pipeline(task, writer_name, reviewer_name)
        return {
            "summary": f"将「{task}」拆解为调研→写作→审查",
            "steps": ["调研", "写作", "审查"],
            "assignments": [
                {
                    "id": "t1",
                    "agent": research_name,
                    "task": f"调研：{task}",
                    "depends_on": [],
                    "reason": "收集写作所需资料与观点",
                },
                {
                    "id": "t2",
                    "agent": writer_name,
                    "task": f"写作：{task}",
                    "depends_on": ["t1"],
                    "reason": "基于调研产出内容",
                },
                {
                    "id": "t3",
                    "agent": reviewer_name,
                    "task": f"审查：{task}",
                    "depends_on": ["t2"],
                    "reason": "内容质量与结构审查",
                },
            ],
        }

    def _analysis_pipeline(
        self,
        task: str,
        research_name: str,
        analyst_name: str,
        reviewer_name: str,
        *,
        skip_research: bool = False,
    ) -> dict[str, Any]:
        if skip_research:
            return {
                "summary": f"将「{task}」拆解为分析→审查",
                "steps": ["分析", "审查"],
                "assignments": [
                    {
                        "id": "t1",
                        "agent": analyst_name,
                        "task": f"分析：{task}",
                        "depends_on": [],
                        "reason": "产出结构化分析报告",
                    },
                    {
                        "id": "t2",
                        "agent": reviewer_name,
                        "task": f"审查：{task}",
                        "depends_on": ["t1"],
                        "reason": "验证分析逻辑与结论",
                    },
                ],
            }
        return {
            "summary": f"将「{task}」拆解为调研→分析→审查",
            "steps": ["调研", "分析", "审查"],
            "assignments": [
                {
                    "id": "t1",
                    "agent": research_name,
                    "task": f"调研：{task}",
                    "depends_on": [],
                    "reason": "收集分析所需信息",
                },
                {
                    "id": "t2",
                    "agent": analyst_name,
                    "task": f"分析：{task}",
                    "depends_on": ["t1"],
                    "reason": "基于资料产出分析报告",
                },
                {
                    "id": "t3",
                    "agent": reviewer_name,
                    "task": f"审查：{task}",
                    "depends_on": ["t2"],
                    "reason": "验证分析质量",
                },
            ],
        }

    def _general_pipeline(self, task: str, reviewer_name: str) -> dict[str, Any]:
        discovered = self._registry.discover(task, limit=3)
        worker_names = [
            agent.name
            for agent, _score in discovered
            if agent.name not in ("Planner", reviewer_name)
        ][:2]
        if not worker_names:
            worker_names = ["Research"]
        if len(worker_names) == 1:
            return {
                "summary": f"将「{task}」拆解为执行→审查",
                "steps": ["执行", "审查"],
                "assignments": [
                    {
                        "id": "t1",
                        "agent": worker_names[0],
                        "task": task,
                        "depends_on": [],
                        "reason": "处理用户任务",
                    },
                    {
                        "id": "t2",
                        "agent": reviewer_name,
                        "task": f"审查：{task}",
                        "depends_on": ["t1"],
                        "reason": "质量检查",
                    },
                ],
            }
        return {
            "summary": f"将「{task}」拆解为多步协作",
            "steps": ["步骤1", "步骤2", "审查"],
            "assignments": [
                {
                    "id": "t1",
                    "agent": worker_names[0],
                    "task": f"第一步：{task}",
                    "depends_on": [],
                    "reason": "初步处理",
                },
                {
                    "id": "t2",
                    "agent": worker_names[1],
                    "task": f"第二步：{task}",
                    "depends_on": ["t1"],
                    "reason": "深化处理",
                },
                {
                    "id": "t3",
                    "agent": reviewer_name,
                    "task": f"审查：{task}",
                    "depends_on": ["t2"],
                    "reason": "最终质量检查",
                },
            ],
        }

    @staticmethod
    def _is_simple_task(task: str) -> bool:
        lower = task.lower()
        return any(keyword in lower for keyword in _SIMPLE_TASK_KEYWORDS)

    def _needs_vision(self, task: str) -> bool:
        lower = task.lower()
        return any(k in lower for k in _VISION_KEYWORDS)

    @staticmethod
    def _lite_pipeline(task: str, coder_name: str, reviewer_name: str) -> dict[str, Any]:
        return {
            "summary": f"快速实现「{task}」",
            "steps": ["编码", "审查"],
            "assignments": [
                {
                    "id": "t1",
                    "agent": coder_name,
                    "task": f"实现：{task}",
                    "depends_on": [],
                    "reason": "简单任务直接编码",
                },
                {
                    "id": "t2",
                    "agent": reviewer_name,
                    "task": f"审查：{task}",
                    "depends_on": ["t1"],
                    "reason": "快速质量检查",
                },
            ],
        }

    @staticmethod
    def _append_tester(
        plan: dict[str, Any],
        task: str,
        tester_name: str,
        coder_id: str,
        review_id: str,
    ) -> tuple[str, str]:
        if not tester_name:
            return coder_id, review_id
        tester_id = f"t{len(plan['assignments']) + 1}"
        plan["summary"] = plan["summary"].replace("→审查", "→测试→审查")
        if "测试" not in plan["steps"]:
            insert_at = len(plan["steps"]) - 1 if plan["steps"] else 0
            plan["steps"].insert(insert_at, "测试")
        plan["assignments"].append(
            {
                "id": tester_id,
                "agent": tester_name,
                "task": f"测试：{task}",
                "depends_on": [coder_id],
                "reason": "在审查前验证实现是否满足基本质量门槛",
            }
        )
        return tester_id, f"t{len(plan['assignments']) + 1}"

    def _vision_pipeline(
        self,
        task: str,
        research_name: str,
        coder_name: str,
        reviewer_name: str,
        tester_name: str,
        vision_name: str,
        *,
        skip_research: bool = False,
    ) -> dict[str, Any]:
        if skip_research:
            plan: dict[str, Any] = {
                "summary": f"将「{task}」拆解为视觉分析→编码→审查",
                "steps": ["视觉", "编码", "审查"],
                "assignments": [
                    {
                        "id": "t1",
                        "agent": vision_name,
                        "task": f"视觉分析：{task}",
                        "depends_on": [],
                        "reason": "任务包含视觉/OCR/检测相关需求",
                    },
                    {
                        "id": "t2",
                        "agent": coder_name,
                        "task": f"实现：{task}",
                        "depends_on": ["t1"],
                        "reason": "基于视觉结果产出实现",
                    },
                ],
            }
            review_dep, review_id = self._append_tester(plan, task, tester_name, "t2", "t3")
        else:
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
                        "agent": vision_name,
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
            review_dep, review_id = self._append_tester(plan, task, tester_name, "t3", "t4")
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

    def _standard_pipeline(
        self,
        task: str,
        research_name: str,
        coder_name: str,
        reviewer_name: str,
        tester_name: str,
        *,
        skip_research: bool = False,
    ) -> dict[str, Any]:
        if skip_research:
            plan: dict[str, Any] = {
                "summary": f"将「{task}」拆解为编码→审查",
                "steps": ["编码", "审查"],
                "assignments": [
                    {
                        "id": "t1",
                        "agent": coder_name,
                        "task": f"实现：{task}",
                        "depends_on": [],
                        "reason": "直接产出实现",
                    },
                ],
            }
            review_dep, review_id = self._append_tester(plan, task, tester_name, "t1", "t2")
        else:
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
            review_dep, review_id = self._append_tester(plan, task, tester_name, "t2", "t3")
            if tester_name:
                plan["summary"] = f"将「{task}」拆解为调研→编码→测试→审查"
                plan["steps"] = ["调研", "编码", "测试", "审查"]
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
