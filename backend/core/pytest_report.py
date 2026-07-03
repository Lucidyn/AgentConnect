"""Parse and summarize pytest output for retries and UI."""

from __future__ import annotations

import re

_FAILED_LINE = re.compile(r"^FAILED\b", re.M)
_ERROR_LINE = re.compile(r"^ERROR\b", re.M)
_assertion_line = re.compile(r"^E\s+\S")


def summarize_pytest_output(stdout: str, stderr: str, *, max_detail_lines: int = 24) -> str:
    """Extract failed tests and assertion lines from pytest output."""
    combined = "\n".join(part for part in (stdout or "", stderr or "") if part).strip()
    if not combined:
        return "（无 pytest 输出）"

    lines = combined.splitlines()
    failed_lines = [
        line.strip()
        for line in lines
        if _FAILED_LINE.match(line.strip())
        or _ERROR_LINE.match(line.strip())
        or ("::" in line and (" FAILED" in line or line.strip().endswith("FAILED")))
    ]

    detail_lines: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if _assertion_line.match(stripped):
            detail_lines.append(stripped)
        elif stripped.startswith(">"):
            detail_lines.append(stripped)
        elif "AssertionError" in stripped or "Error:" in stripped:
            detail_lines.append(stripped)

    parts: list[str] = []
    if failed_lines:
        parts.append("失败用例：")
        parts.extend(failed_lines[:12])
    if detail_lines:
        parts.append("")
        parts.append("错误摘要：")
        parts.extend(detail_lines[:max_detail_lines])

    if parts:
        return "\n".join(parts)

    tail = lines[-max_detail_lines:] if len(lines) > max_detail_lines else lines
    return "\n".join(tail)


def format_pytest_result(
    *,
    passed: bool,
    workspace: str = "",
    stdout: str = "",
    stderr: str = "",
    exit_code: int = 0,
    max_body_chars: int = 6000,
) -> str:
    """Build structured test result text for agents and orchestrator."""
    verdict = "通过" if passed else "失败"
    status = "PASSED" if passed else "FAILED"
    header_lines = [f"【测试结果】{verdict}", f"{status}: pytest"]
    if workspace:
        header_lines.append(f"工作区：{workspace}")

    if passed:
        body = (stdout or stderr or "").strip()
        if body:
            header_lines.append(body[:800])
        return "\n".join(header_lines)

    summary = summarize_pytest_output(stdout, stderr)
    header_lines.append("")
    header_lines.append(summary)
    if exit_code not in (0, 1):
        header_lines.append(f"\npytest exit code: {exit_code}")

    text = "\n".join(header_lines)
    if len(text) > max_body_chars:
        text = text[: max_body_chars - 20].rstrip() + "\n…（输出已截断）"
    return text


def extract_test_failure_for_retry(result: str) -> str:
    """Prefer structured pytest summary for Coder retry prompts."""
    if "错误摘要：" in result or "失败用例：" in result:
        idx = result.find("失败用例：")
        if idx == -1:
            idx = result.find("错误摘要：")
        if idx >= 0:
            return result[idx:].strip()
    match = re.search(r"【测试结果】\s*失败[\s\S]*", result)
    if match:
        return match.group(0).strip()
    return result.strip()
