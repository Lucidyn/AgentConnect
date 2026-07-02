"""TestRunner Agent — lightweight validation loop for generated code."""

from __future__ import annotations

import ast
import py_compile
import re
import tempfile
from pathlib import Path

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
        result = self._run_validation(message.content)

        if is_test_failed(result):
            await self.request_planner_retry(message, result)
            return None

        await self.reply_to_planner(message, result)
        return None

    @staticmethod
    def _extract_python_blocks(content: str) -> list[str]:
        blocks = re.findall(r"```(?:python)?\s*\n(.*?)```", content, re.S | re.I)
        if blocks:
            return [block.strip() for block in blocks if block.strip()]
        stripped = content.strip()
        if "def " in stripped or "import " in stripped or "class " in stripped:
            return [stripped]
        return []

    @staticmethod
    def _validate_python(code: str) -> str | None:
        try:
            ast.parse(code)
        except SyntaxError as exc:
            return f"SyntaxError: {exc.msg} (line {exc.lineno})"
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "snippet.py"
            path.write_text(code, encoding="utf-8")
            try:
                py_compile.compile(str(path), doraise=True)
            except py_compile.PyCompileError as exc:
                return str(exc)
        return None

    @classmethod
    def _run_validation(cls, content: str) -> str:
        for block in cls._extract_python_blocks(content):
            error = cls._validate_python(block)
            if error:
                return f"【测试结果】失败\nFAILED: Python validation failed — {error}"

        return cls._mock_test(content)

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
                return "【测试结果】失败\nFAILED: FastAPI service should expose a GET /health endpoint."
        if "uploadfile" in lower:
            has_validation = (
                "content_type" in lower
                or "httpexception" in lower
                or "validate" in lower
            )
            if not has_validation:
                return (
                    "【测试结果】失败\n"
                    "FAILED: UploadFile handling should validate content_type or raise HTTPException."
                )
        return "【测试结果】通过\nPASSED: lightweight validation checks passed."


def is_test_failed(result: str) -> bool:
    """Parse structured test verdict; fall back to legacy FAILED prefix."""
    match = re.search(r"【测试结果】\s*(通过|失败|PASSED|FAILED)", result, re.I)
    if match:
        verdict = match.group(1).lower()
        return verdict in ("失败", "failed")
    return result.strip().upper().startswith("FAILED")
