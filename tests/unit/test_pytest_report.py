"""Tests for pytest output summarization."""

from backend.core.pytest_report import (
    extract_test_failure_for_retry,
    format_pytest_result,
    summarize_pytest_output,
)


def test_summarize_pytest_output_extracts_failed_tests():
    stdout = """
tests/test_api.py::test_health FAILED
tests/test_api.py:12: AssertionError
E   assert 404 == 200
"""
    summary = summarize_pytest_output(stdout, "")
    assert "失败用例：" in summary
    assert "test_health" in summary
    assert "AssertionError" in summary or "assert 404" in summary


def test_format_pytest_result_failure_includes_summary():
    text = format_pytest_result(
        passed=False,
        workspace="/tmp/app",
        stdout="FAILED tests/test_x.py::test_y - assert False",
        stderr="",
        exit_code=1,
    )
    assert "【测试结果】失败" in text
    assert "工作区：/tmp/app" in text
    assert "FAILED" in text


def test_extract_test_failure_for_retry_prefers_summary_section():
    result = format_pytest_result(
        passed=False,
        stdout="FAILED tests/a.py::test_b\nE   assert 1 == 2",
        stderr="",
        exit_code=1,
    )
    extracted = extract_test_failure_for_retry(result)
    assert "失败用例：" in extracted or "FAILED" in extracted
