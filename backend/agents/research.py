"""Research Agent — Arxiv/GitHub tools + shared memory."""

from __future__ import annotations

import logging

from backend.constants import PLANNER
from backend.core.agent import Agent
from backend.core.query_extract import extract_yolo_version
from backend.core.query_extract import extract_tool_query as build_tool_query
from backend.models.message import Message, MessageType

logger = logging.getLogger(__name__)

_MAX_TOOL_CONTEXT = 6000

SYSTEM_PROMPT = """你是 Research Agent。输出简短调研要点（每条一行）：
- 关键发现
- 参考链接（如有）
- 给 Coder 的 1-3 条建议
不要长段落。
若用户指定了具体版本（如 YOLO26、YOLO11），必须原样使用该版本号，不得替换为 YOLOv6 或其他版本。"""


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

        tool_query = build_tool_query(task)
        tool_results = await self.tools.run_for_task(tool_query)
        tool_context = "\n\n".join(r.content for r in tool_results if r.success)
        if len(tool_context) > _MAX_TOOL_CONTEXT:
            tool_context = tool_context[:_MAX_TOOL_CONTEXT].rstrip() + "\n…（工具结果已截断）"

        shared_context = await self.recall_shared(tool_query)
        prompt_parts = [f"调研任务：{task}"]
        if tool_context:
            prompt_parts.append(f"工具检索结果：\n{tool_context}")
        if shared_context:
            prompt_parts.append(f"相关共享记忆：\n{shared_context}")

        fallback = tool_context or self._fallback_research(task)
        result = await self.llm_chat(
            SYSTEM_PROMPT,
            "\n\n".join(prompt_parts),
            fallback,
            role=self.role,
            message=message,
        )

        await self.store_in_shared_memory(
            content=result,
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
            ver = extract_yolo_version(task)
            label = f"YOLO{ver}" if ver else "YOLO"
            return f"【调研】{label} 目标检测 — ultralytics SDK, ONNX/TensorRT 部署"
        if "ocr" in task_lower or "paddle" in task_lower:
            return "【调研】PaddleOCR 3.x — PP-OCRv5, pip/ONNX 部署"
        if "qwen" in task_lower or "vlm" in task_lower:
            return "【调研】Qwen-VL 多模态 — OpenAI 兼容 API, vLLM 本地部署"
        return f"【调研】{task} — 推荐 FastAPI + Docker 模块化架构"
