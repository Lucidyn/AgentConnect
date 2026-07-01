"""TestRunner Agent — lightweight validation loop for generated code."""

from __future__ import annotations

import re

from backend.constants import TEST_RUNNER
from backend.core.agent import Agent
from backend.models.message import Message


class TestRunnerAgent(Agent):
    __test__ = False

    name = TEST_RUNNER
    role = "tester"
    capabilities = ["testing", "validation", "quality_gate"]
    description = "运行轻量验证，输出测试结果与失败原因"
    inputs = ["code_patch"]
    outputs = ["test_result"]
    accepts = ["assignment_start"]

    async def think(self, message: Message) -> str | None:
        result = self._mock_test(message.content)

        if result.startswith("FAILED"):
            await self.request_planner_retry(message, result)
            return None

        await self.reply_to_planner(message, result)
        return None

    @staticmethod
    def _mock_test(content: str) -> str:
        lower = content.lower()
        if "fastapi" in lower:
            has_health = (
                "/health" in lower
                or bool(re.search(r"@app\.(get|route)\s*\(\s*['\"]/health", content, re.I))
                or "def health" in lower
            )
            if not has_health:
                return "FAILED: FastAPI service should expose a GET /health endpoint."
        if "uploadfile" in lower:
            has_validation = (
                "content_type" in lower
                or "httpexception" in lower
                or "validate" in lower
            )
            if not has_validation:
                return "FAILED: UploadFile handling should validate content_type or raise HTTPException."
        return "PASSED: lightweight validation checks passed."
