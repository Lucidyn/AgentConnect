"""Reviewer Agent — code review and quality assurance."""

from __future__ import annotations

import re

from backend.constants import REVIEWER
from backend.core.agent import Agent
from backend.models.message import Message

SYSTEM_PROMPT = """你是 Reviewer Agent。审查交付物质量（代码、文章、报告等）。
检查：完整性、逻辑、安全性（如适用）、可读性。
有基本结构且无明显问题则通过。
输出：【审查结果】通过/需要修改 + 简短问题列表（如有）。"""


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

        result = await self.llm.chat(
            SYSTEM_PROMPT,
            f"请审查以下内容：\n{content}",
            fallback,
            role=self.role,
        )

        self.remember("last_review", result)
        failed = review_failed(result)

        if failed:
            await self.request_planner_retry(
                message, f"审查发现问题，请修改：\n{result}"
            )
            return None

        await self.reply_to_planner(message, result)
        return None

    def _mock_review(self, content: str) -> str:
        issues = []
        lower = content.lower()
        if "try" not in lower and "except" not in lower and ("def " in lower or "class " in lower):
            issues.append("代码缺少异常处理")
        if len(content.strip()) < 80:
            issues.append("内容过短，可能不完整")
        if "UploadFile" in content and "validate" not in lower:
            if "content_type" not in content and "HTTPException" not in content:
                issues.append("文件上传缺少校验")

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


def review_failed(result: str) -> bool:
    """Parse structured review verdict; fall back to legacy heuristics."""
    match = re.search(r"【审查结果】\s*(通过|需要修改)", result)
    if match:
        return match.group(1) == "需要修改"
    if re.search(r"审查结果[：:]\s*通过", result):
        return False
    if "需要修改" in result and "通过" not in result.split("需要修改", 1)[0]:
        return True
    return "Bug" in result
