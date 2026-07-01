"""Reviewer Agent — code review and quality assurance."""

from __future__ import annotations

from backend.constants import PLANNER, REVIEWER
from backend.core.agent import Agent
from backend.models.message import Message, MessageIntent, MessageType

SYSTEM_PROMPT = """你是 Reviewer Agent，负责代码审查和质量把关。
审查要点：
1. 代码正确性和完整性
2. 安全性（输入校验、错误处理）
3. 可维护性
4. 部署可行性

输出格式：
- 总体评价
- 发现的问题（如有）
- 改进建议
- 是否通过审查"""


class ReviewerAgent(Agent):
    name = REVIEWER
    role = "reviewer"
    capabilities = ["code_review", "quality_assurance", "security_audit"]
    description = "代码审查、质量检查、安全审计"
    inputs = ["code_patch", "test_result"]
    outputs = ["review_result", "review_feedback"]
    accepts = ["assignment_start"]

    async def think(self, message: Message) -> str | None:
        content = message.content
        fallback = self._mock_review(content)
        assignment_id = message.metadata.get("assignment_id", "")
        attempt = message.metadata.get("attempt", 0)

        result = await self.llm.chat(
            SYSTEM_PROMPT,
            f"请审查以下内容：\n{content}",
            fallback,
        )

        self.remember("last_review", result)
        retries = self.recall("retry_count", 0)
        failed = ("Bug" in result or "需要修改" in result) and "通过" not in result

        if failed and retries < 1:
            self.remember("retry_count", retries + 1)
            await self.send(
                PLANNER,
                f"审查发现问题，请修改：\n{result}",
                message_type=MessageType.RESPONSE,
                metadata={
                    "intent": MessageIntent.RETRY_REQUEST.value,
                    "needs_retry": True,
                    "assignment_id": assignment_id,
                    "attempt": attempt,
                    "reply_to": message.id,
                },
            )
            return None

        self.remember("retry_count", 0)

        if failed:
            await self.send(
                PLANNER,
                result,
                message_type=MessageType.RESPONSE,
                metadata={
                    "intent": MessageIntent.APPROVAL_REQUEST.value,
                    "needs_approval": True,
                    "assignment_id": assignment_id,
                    "attempt": attempt,
                    "reply_to": message.id,
                },
            )
            return None

        await self.reply_to_planner(message, result)
        return None

    def _mock_review(self, content: str) -> str:
        issues = []
        if "except" not in content.lower() and "try" not in content.lower():
            issues.append("缺少异常处理")
        if "UploadFile" in content and "validate" not in content.lower():
            if "content_type" not in content and "HTTPException" not in content:
                issues.append("文件上传缺少校验（文件类型/大小）")

        if issues:
            return (
                "【审查结果】需要修改\n"
                f"发现问题：{'; '.join(issues)}\n"
                "建议：添加 try/except 错误处理，增加文件类型和大小校验。"
            )
        return (
            "【审查结果】通过 ✓\n"
            "代码结构清晰，API 设计合理。\n"
            "建议：生产环境添加日志和监控。"
        )
