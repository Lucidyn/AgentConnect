"""OpenTelemetry helper tests."""

from backend.core.otel import start_agent_span, start_orchestration_span, start_span, start_tool_span


def test_spans_noop_without_tracer():
    with start_span("demo", {"task.id": "t1"}) as span:
        assert span is None
    with start_agent_span("Research", "t1", "a1", "default") as span:
        assert span is None
    with start_orchestration_span(
        "dispatch", task_id="t1", assignment_id="a1", tenant_id="default", agent="Coder"
    ) as span:
        assert span is None
    with start_tool_span("arxiv", "t1") as span:
        assert span is None
