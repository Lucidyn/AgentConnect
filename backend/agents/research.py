"""Research Agent — Arxiv/GitHub tools + shared memory."""

from __future__ import annotations

import logging
import re

from backend.constants import PLANNER
from backend.core.agent import Agent
from backend.models.message import Message, MessageType

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """你是 Research Agent，负责信息调研、文档查找和技术研究。
根据工具检索结果和共享记忆，输出结构化调研报告：
1. 关键发现
2. 参考资料链接
3. 技术要点
4. 给 Coder 的建议"""


class ResearchAgent(Agent):
    name = "Research"
    role = "researcher"
    capabilities = ["search", "documentation", "paper_lookup", "api_research", "arxiv", "github"]
    description = "搜索资料、查 Arxiv 论文、查 GitHub 开源项目"
    inputs = ["task"]
    outputs = ["research_report"]
    accepts = ["assignment_start", "agent_query"]

    async def think(self, message: Message) -> str | None:
        task = message.content
        self.remember("last_task", task)

        tool_query = self._extract_tool_query(task)
        tool_results = await self.tools.run_for_task(tool_query)
        tool_context = "\n\n".join(r.content for r in tool_results if r.success)

        shared_context = await self.recall_shared(tool_query)
        prompt_parts = [f"调研任务：{task}"]
        if tool_context:
            prompt_parts.append(f"工具检索结果：\n{tool_context}")
        if shared_context:
            prompt_parts.append(f"相关共享记忆：\n{shared_context}")

        fallback = tool_context or self._fallback_research(task)
        result = await self.llm.chat(
            SYSTEM_PROMPT,
            "\n\n".join(prompt_parts),
            fallback,
        )

        await self.shared_memory.store(
            content=result,
            agent=self.name,
            metadata={"task": task, "tools": [r.tool for r in tool_results]},
            task_id=self._current_task_id,
        )
        self.remember("last_result", result)

        if message.from_agent == PLANNER:
            await self.reply_to_planner(message, result)
            return None

        return result

    def _fallback_research(self, task: str) -> str:
        task_lower = task.lower()
        if "yolo" in task_lower:
            return "【调研】YOLO 目标检测 — ultralytics SDK, ONNX/TensorRT 部署"
        if "ocr" in task_lower or "paddle" in task_lower:
            return "【调研】PaddleOCR 3.x — PP-OCRv5, pip/ONNX 部署"
        if "qwen" in task_lower or "vlm" in task_lower:
            return "【调研】Qwen-VL 多模态 — OpenAI 兼容 API, vLLM 本地部署"
        return f"【调研】{task} — 推荐 FastAPI + Docker 模块化架构"

    @staticmethod
    def _extract_tool_query(task: str) -> str:
        for prefix in ("调研：", "调研:", "查一下", "查 ", "实现：", "实现:"):
            if task.startswith(prefix):
                task = task[len(prefix):]
        clause = task.split("，")[0].split(",")[0].strip()
        english = re.findall(r"[A-Za-z][A-Za-z0-9+.-]*", clause)
        if english:
            return english[0]
        return clause or task
