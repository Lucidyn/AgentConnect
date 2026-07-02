"""Optional OpenTelemetry bootstrap."""

from __future__ import annotations

import logging
from contextlib import contextmanager

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


@contextmanager
def start_agent_span(agent: str, task_id: str = "", assignment_id: str = ""):
    if _tracer is None:
        yield None
        return
    with _tracer.start_as_current_span("agent.think") as span:
        span.set_attribute("agent.name", agent)
        if task_id:
            span.set_attribute("task.id", task_id)
        if assignment_id:
            span.set_attribute("assignment.id", assignment_id)
        yield span
