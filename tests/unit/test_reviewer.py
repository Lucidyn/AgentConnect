"""Reviewer verdict parsing tests."""

from backend.agents.reviewer import review_failed


def test_review_failed_structured_pass():
    assert review_failed("【审查结果】通过 ✓\n无问题") is False


def test_review_failed_structured_fail():
    assert review_failed("【审查结果】需要修改\n缺少异常处理") is True


def test_review_failed_pass_with_bug_word_in_context():
    assert review_failed("【审查结果】通过 ✓\n已修复 Bug 描述问题") is False


def test_review_failed_legacy_heuristic():
    assert review_failed("Found Bug in handler") is True
