"""Translator Agent — translate content between languages."""

from __future__ import annotations

from backend.constants import PLANNER
from backend.core.agent import Agent
from backend.models.message import Message, MessageType

SYSTEM_PROMPT = """你是 Translator Agent，负责高质量翻译。
输出结构：
1. 目标语言说明（如适用）
2. 译文正文（保留原文结构与格式）
语言与用户任务一致；若未指定目标语言，默认译为英文。"""


class TranslatorAgent(Agent):
    name = "Translator"
    role = "translator"
    capabilities = ["translation", "localization", "bilingual", "multilingual"]
    description = "将文本翻译为目标语言，保留结构与术语"
    inputs = ["draft", "source_text", "review_feedback"]
    outputs = ["translation"]
    accepts = ["assignment_start", "retry_request", "agent_query"]

    async def think(self, message: Message) -> str | None:
        task = message.content
        shared = await self.recall_shared(task)
        context_parts = [p for p in (shared,) if p]
        if "修改意见" in task or "review" in task.lower():
            context_parts.insert(0, task)

        fallback = self._mock_translation(task)
        user_prompt = task if not context_parts else f"{task}\n\n" + "\n\n".join(context_parts)
        result = await self.llm_chat(SYSTEM_PROMPT, user_prompt, fallback, role=self.role, message=message)

        await self.store_in_shared_memory(
            content=result,
            metadata={"task": task[:200]},
            task_id=self._current_task_id,
        )

        if message.from_agent == PLANNER:
            await self.reply_to_planner(message, result)
            return None
        return result

    @staticmethod
    def _mock_translation(task: str) -> str:
        return (
            "## Translation\n\n"
            "Translated content based on upstream draft.\n\n"
            f"Source task: {task[:120]}\n"
        )
