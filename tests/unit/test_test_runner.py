"""TestRunner verdict parsing tests."""

from backend.agents.test_runner import is_test_failed


def test_structured_pass():
    assert is_test_failed("【测试结果】通过\nPASSED: ok") is False


def test_structured_fail():
    assert is_test_failed("【测试结果】失败\nFAILED: missing health") is True


def test_legacy_failed_prefix():
    assert is_test_failed("FAILED: legacy format") is True
