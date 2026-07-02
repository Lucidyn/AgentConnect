"""Optional OpenTelemetry bootstrap."""

from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Any, Iterator

from backend.config import settings

logger = logging.getLogger(__name__)
_tracer = None


def setup_otel() -> None:
    global _tracer
    endpoint = (settings.otel_exporter_otlp_endpoint or "").strip()
    if not endpoint:
        return
    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
    except ImportError:
        logger.warning(
            "OTEL_EXPORTER_OTLP_ENDPOINT set but opentelemetry packages not installed"
        )
        return

    resource = Resource.create({"service.name": settings.otel_service_name})
    provider = TracerProvider(resource=resource)
    provider.add_span_processor(
        BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint))
    )
    trace.set_tracer_provider(provider)
    _tracer = trace.get_tracer(settings.otel_service_name)
    logger.info("OpenTelemetry tracing enabled → %s", endpoint)


def instrument_fastapi(app) -> None:
    if not (settings.otel_exporter_otlp_endpoint or "").strip():
        return
    try:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

        FastAPIInstrumentor.instrument_app(app)
    except ImportError:
        logger.warning("FastAPI OTEL instrumentation unavailable")


def _set_attrs(span, attributes: dict[str, Any]) -> None:
    for key, value in attributes.items():
        if value is not None and value != "":
            span.set_attribute(key, value)


@contextmanager
def start_span(name: str, attributes: dict[str, Any] | None = None) -> Iterator[Any]:
    if _tracer is None:
        yield None
        return
    with _tracer.start_as_current_span(name) as span:
        _set_attrs(span, attributes or {})
        yield span


@contextmanager
def start_agent_span(
    agent: str,
    task_id: str = "",
    assignment_id: str = "",
    tenant_id: str = "",
) -> Iterator[Any]:
    with start_span(
        "agent.think",
        {
            "agent.name": agent,
            "task.id": task_id,
            "assignment.id": assignment_id,
            "tenant.id": tenant_id,
        },
    ) as span:
        yield span


@contextmanager
def start_orchestration_span(
    operation: str,
    *,
    task_id: str = "",
    assignment_id: str = "",
    tenant_id: str = "",
    agent: str = "",
) -> Iterator[Any]:
    with start_span(
        f"plan.{operation}",
        {
            "task.id": task_id,
            "assignment.id": assignment_id,
            "tenant.id": tenant_id,
            "agent.name": agent,
        },
    ) as span:
        yield span


@contextmanager
def start_tool_span(tool_name: str, task_id: str = "") -> Iterator[Any]:
    with start_span("tool.run", {"tool.name": tool_name, "task.id": task_id}) as span:
        yield span
