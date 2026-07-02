"""Legal Agent — custom plugin example for contract and compliance review."""

from __future__ import annotations

from backend.constants import PLANNER
from backend.core.agent import Agent
from backend.models.message import Message, MessageType

SYSTEM_PROMPT = """你是 Legal Agent，负责法律与合规相关的文本工作。
输出结构：
1. 问题界定（用户到底需要什么法律输出）
2. 要点分析（分条，避免长篇堆砌）
3. 风险与建议（如有）
4. 免责声明：本输出仅供参考，不构成正式法律意见

语言与用户任务一致，术语准确，表述克制。"""


class LegalAgent(Agent):
    name = "Legal"
    role = "legal"
    capabilities = ["contract_review", "compliance", "policy_draft", "legal_summary"]
    description = "合同审查、合规要点、政策条款与法律风险摘要"
    inputs = ["draft", "contract", "brief", "research_report"]
    outputs = ["legal_memo", "compliance_notes"]
    accepts = ["assignment_start", "retry_request", "agent_query"]

    async def think(self, message: Message) -> str | None:
        if message.message_type not in (MessageType.TASK, MessageType.RESPONSE):
            return None

        task = message.content
        shared = await self.recall_shared(task)
        jurisdiction = self.plugin_config.get("jurisdiction", "通用")
        focus = self.plugin_config.get("focus", "合同与合规")

        parts = [f"法律任务：{task}", f"适用法域/场景：{jurisdiction}", f"关注重点：{focus}"]
        if shared:
            parts.append(f"参考资料：\n{shared}")

        result = await self.llm_chat(
            SYSTEM_PROMPT,
            "\n\n".join(parts),
            self._fallback_memo(task, jurisdiction=jurisdiction, focus=focus),
            role=self.role,
            message=message,
        )

        await self.store_in_shared_memory(
            content=result,
            metadata={"task": task[:200], "jurisdiction": jurisdiction},
            task_id=self._current_task_id,
        )

        if message.from_agent == PLANNER:
            await self.reply_to_planner(message, result)
            return None
        return result

    @staticmethod
    def _fallback_memo(task: str, *, jurisdiction: str, focus: str) -> str:
        return (
            f"# 法律备忘录（草案）\n\n"
            f"**任务**：{task[:120]}\n"
            f"**法域/场景**：{jurisdiction}\n"
            f"**关注**：{focus}\n\n"
            "## 要点\n"
            "1. 明确合同主体、标的与交付标准\n"
            "2. 检查责任限制、终止与争议解决条款\n"
            "3. 标注需人工律师复核的高风险项\n\n"
            "*免责声明：本输出由 AI 生成，仅供参考，不构成正式法律意见。*"
        )
