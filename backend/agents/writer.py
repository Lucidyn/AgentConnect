"""Writer Agent — content creation for articles, copy, and docs."""

from __future__ import annotations

from backend.constants import PLANNER
from backend.core.agent import Agent
from backend.models.message import Message, MessageType

SYSTEM_PROMPT = """你是 Writer Agent，负责创作高质量文本内容。
输出结构：
1. 标题（如适用）
2. 正文（清晰分段）
3. 可选：摘要或行动建议
语言与用户任务一致，简洁专业。"""


class WriterAgent(Agent):
    name = "Writer"
    role = "writer"
    capabilities = ["writing", "content", "copywriting", "documentation", "blog"]
    description = "撰写文章、文案、文档与营销内容"
    inputs = ["research_report", "brief", "review_feedback"]
    outputs = ["draft", "content"]
    accepts = ["assignment_start", "retry_request", "agent_query"]

    async def think(self, message: Message) -> str | None:
        task = message.content
        shared = await self.recall_shared(task)
        context_parts = [p for p in (shared,) if p]
        if "修改意见" in task or "review" in task.lower():
            context_parts.insert(0, task)

        fallback = self._mock_draft(task)
        user_prompt = task if not context_parts else f"{task}\n\n" + "\n\n".join(context_parts)
        result = await self.llm.chat(SYSTEM_PROMPT, user_prompt, fallback, role=self.role)

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
    def _mock_draft(task: str) -> str:
        title = task.split("：")[-1].split(":")[-1].strip()[:60] or task[:60]
        return (
            f"# {title}\n\n"
            "正文草案：围绕用户需求展开，结构清晰，包含引言、核心观点与总结。\n\n"
            "## 要点\n"
            "- 明确目标读者\n"
            "- 提供可执行建议\n"
        )
