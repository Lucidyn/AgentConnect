"""Analyst Agent — structured analysis, comparison, and decision support."""

from __future__ import annotations

from backend.constants import PLANNER
from backend.core.agent import Agent
from backend.models.message import Message, MessageType

SYSTEM_PROMPT = """你是 Analyst Agent，负责结构化分析与决策支持。
输出结构：
1. 问题定义
2. 关键发现（分点）
3. 对比/权衡（如适用）
4. 结论与建议
基于已有资料分析，不要编造数据来源。"""


class AnalystAgent(Agent):
    name = "Analyst"
    role = "analyst"
    capabilities = ["analysis", "comparison", "reporting", "insights", "evaluation"]
    description = "数据分析、竞品对比、调研报告与决策建议"
    inputs = ["research_report", "data", "brief"]
    outputs = ["analysis_report", "recommendations"]
    accepts = ["assignment_start", "retry_request", "agent_query"]

    async def think(self, message: Message) -> str | None:
        task = message.content
        shared = await self.recall_shared(task)
        parts = [f"分析任务：{task}"]
        if shared:
            parts.append(f"参考资料：\n{shared}")

        fallback = self._mock_analysis(task)
        result = await self.llm_chat(
            SYSTEM_PROMPT,
            "\n\n".join(parts),
            fallback,
            role="analyst",
            message=message,
        )

        await self.shared_memory.store(
            content=result,
            agent=self.name,
            metadata={"task": task[:200]},
            task_id=self._current_task_id,
        )

        if message.from_agent == PLANNER:
            await self.reply_to_planner(message, result)
            return None
        return result

    @staticmethod
    def _mock_analysis(task: str) -> str:
        return (
            f"【分析报告】{task[:80]}\n\n"
            "1. 问题定义：明确分析目标与范围\n"
            "2. 关键发现：列出 3-5 条核心洞察\n"
            "3. 建议：给出可执行的下一步行动\n"
        )
