"""Metrics tests."""

from backend.core.metrics import TASKS_SUBMITTED, metrics_response


def test_metrics_output():
    TASKS_SUBMITTED.inc()
    body, content_type = metrics_response()
    assert b"ac_tasks_submitted_total" in body
    assert "text/plain" in content_type
