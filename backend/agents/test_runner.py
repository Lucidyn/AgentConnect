"""TestRunner Agent — lightweight validation loop for generated code."""

from __future__ import annotations

from backend.constants import PLANNER
from backend.core.agent import Agent
from backend.models.message import Message, MessageIntent, MessageType


class TestRunnerAgent(Agent):
    __test__ = False

    name = "TestRunner"
    role = "tester"
    capabilities = ["testing", "validation", "quality_gate"]
    description = "运行轻量验证，输出测试结果与失败原因"
    inputs = ["code_patch"]
    outputs = ["test_result"]
    accepts = ["assignment_start"]

    async def think(self, message: Message) -> str | None:
        content = message.content
        assignment_id = message.metadata.get("assignment_id", "")
        attempt = message.metadata.get("attempt", 0)
        result = self._mock_test(content)

        if result.startswith("FAILED"):
            await self.send(
                PLANNER,
                result,
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

        await self.reply_to_planner(message, result)
        return None

    @staticmethod
    def _mock_test(content: str) -> str:
        lower = content.lower()
        if "fastapi" in lower and "/health" not in lower:
            return "FAILED: FastAPI service should expose a health endpoint."
        if "uploadfile" in lower and "content_type" not in lower:
            return "FAILED: UploadFile handling should validate content_type."
        return "PASSED: lightweight validation checks passed."
