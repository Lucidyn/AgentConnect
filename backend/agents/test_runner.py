"""TestRunner Agent — validation loop with optional pytest execution."""

from __future__ import annotations

import ast
import logging
import py_compile
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from backend.config import settings
from backend.constants import TEST_RUNNER
from backend.core.agent import Agent
from backend.models.message import Message

logger = logging.getLogger(__name__)


class TestRunnerAgent(Agent):
    __test__ = False

    name = TEST_RUNNER
    role = "tester"
    capabilities = ["testing", "validation", "quality_gate"]
    description = "运行 pytest 或轻量验证，输出测试结果与失败原因"
    inputs = ["code_patch"]
    outputs = ["test_result"]
    accepts = ["assignment_start"]

    async def think(self, message: Message) -> str | None:
        result = self._run_pytest(message.content) or self._run_validation(message.content)

        if is_test_failed(result):
            await self.request_planner_retry(message, result)
            return None

        await self.reply_to_planner(message, result)
        return None

    def _pytest_enabled(self) -> bool:
        cfg = self.plugin_config
        if "pytest_enabled" in cfg:
            return bool(cfg["pytest_enabled"])
        return settings.test_runner_pytest

    def _sandbox_mode(self) -> str:
        cfg = self.plugin_config
        mode = str(cfg.get("sandbox") or settings.test_runner_sandbox or "subprocess").lower()
        return mode

    def _timeout(self) -> int:
        cfg = self.plugin_config
        return int(cfg.get("timeout") or settings.test_runner_timeout)

    def _docker_image(self) -> str:
        cfg = self.plugin_config
        return str(cfg.get("docker_image") or settings.test_runner_docker_image)

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

    def _run_pytest(self, content: str) -> str | None:
        if not self._pytest_enabled() or self._sandbox_mode() == "off":
            return None
        blocks = self._extract_python_blocks(content)
        if not blocks and "def test_" not in content:
            return None
        if not blocks:
            blocks = [content.strip()]
        if not any("def test_" in block for block in blocks):
            return None

        with tempfile.TemporaryDirectory(prefix="ac-pytest-") as tmp:
            root = Path(tmp)
            for index, block in enumerate(blocks, start=1):
                name = f"test_block_{index}.py" if "def test_" in block else f"module_{index}.py"
                (root / name).write_text(block, encoding="utf-8")

            output = self._execute_pytest(root)
            if output is None:
                return None
            passed = output.returncode == 0
            verdict = "通过" if passed else "失败"
            status = "PASSED" if passed else "FAILED"
            body = (output.stdout or "") + (output.stderr or "")
            body = body.strip() or f"pytest exit code {output.returncode}"
            return f"【测试结果】{verdict}\n{status}: pytest\n{body[:4000]}"

    def _execute_pytest(self, root: Path) -> subprocess.CompletedProcess[str] | None:
        if shutil.which("pytest") is None:
            logger.info("pytest not installed — falling back to lightweight validation")
            return None

        mode = self._sandbox_mode()
        timeout = self._timeout()
        if mode == "docker":
            if not shutil.which("docker"):
                logger.warning("docker not available — falling back to subprocess pytest")
                mode = "subprocess"
            else:
                cmd = [
                    "docker",
                    "run",
                    "--rm",
                    "-v",
                    f"{root}:/work",
                    "-w",
                    "/work",
                    self._docker_image(),
                    "python",
                    "-m",
                    "pytest",
                    "-q",
                    ".",
                ]
                try:
                    return subprocess.run(
                        cmd,
                        capture_output=True,
                        text=True,
                        timeout=timeout,
                    )
                except subprocess.TimeoutExpired:
                    return subprocess.CompletedProcess(cmd, 124, "", "pytest timed out")

        cmd = [sys.executable, "-m", "pytest", "-q", str(root)]
        try:
            return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            return subprocess.CompletedProcess(cmd, 124, "", "pytest timed out")

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
