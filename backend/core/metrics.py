"""Prometheus metrics — optional observability."""

from __future__ import annotations

from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest

TASKS_SUBMITTED = Counter("ac_tasks_submitted_total", "Tasks submitted")
TASKS_FINISHED = Counter("ac_tasks_finished_total", "Tasks finished", ["status"])
QUEUE_ACTIVE = Gauge("ac_queue_active", "Active tasks in queue")
QUEUE_QUEUED = Gauge("ac_queue_queued", "Queued tasks waiting")
MESSAGES_SENT = Counter("ac_messages_sent_total", "Messages published", ["from_agent", "to_agent"])
OUTBOX_PENDING = Gauge("ac_outbox_pending", "Outbox pending messages")
OUTBOX_FAILED = Gauge("ac_outbox_failed", "Outbox failed messages")
LLM_REQUESTS = Counter("ac_llm_requests_total", "LLM requests", ["provider", "result"])
LLM_TOKENS = Counter(
    "ac_llm_tokens_total",
    "LLM tokens consumed",
    ["provider", "direction"],
)
AGENT_THINK_SECONDS = Histogram(
    "ac_agent_think_seconds",
    "Agent think() duration",
    ["agent"],
    buckets=(0.1, 0.5, 1, 2, 5, 10, 30),
)


def metrics_response() -> tuple[bytes, str]:
    return generate_latest(), CONTENT_TYPE_LATEST
