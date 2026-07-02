"""Pipeline profiling — measure where time goes in an end-to-end agent task."""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from backend.models.message import Message, MessageIntent, MessageType
from backend.models.plan import TaskPlan
from backend.models.task import TaskStatus


@dataclass
class TimingEvent:
    name: str
    elapsed_ms: float
    delta_ms: float
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class LLMCallRecord:
    elapsed_ms: float
    provider: str
    used_fallback: bool
    prompt_chars: int


@dataclass
class AgentThinkRecord:
    agent: str
    elapsed_ms: float
    message_type: str
    from_agent: str


class PipelineProfiler:
    """Collect timing events for a single pipeline run."""

    def __init__(self) -> None:
        self._t0 = time.perf_counter()
        self._last = self._t0
        self.events: list[TimingEvent] = []
        self.llm_calls: list[LLMCallRecord] = []
        self.agent_thinks: list[AgentThinkRecord] = []
        self.messages: list[dict[str, Any]] = []
        self._assignment_seen: set[tuple[str, str]] = set()
        self._status_seen: set[str] = set()
        self._assignment_start_ms: dict[str, float] = {}
        self._assignment_result_ms: dict[str, dict[str, Any]] = {}
        self._unwatch: Callable[[], None] | None = None

    def mark(self, name: str, **metadata: Any) -> None:
        now = time.perf_counter()
        elapsed_ms = (now - self._t0) * 1000
        delta_ms = (now - self._last) * 1000
        self._last = now
        self.events.append(
            TimingEvent(name=name, elapsed_ms=elapsed_ms, delta_ms=delta_ms, metadata=metadata)
        )

    def attach_platform(self, platform) -> None:
        """Hook message log and LLM calls on a running platform."""

        async def on_message(message: Message) -> None:
            if not message.task_id:
                return
            elapsed_ms = (time.perf_counter() - self._t0) * 1000
            intent = message.metadata.get("intent", "")
            assignment_id = message.metadata.get("assignment_id", "")

            self.messages.append(
                {
                    "elapsed_ms": round(elapsed_ms, 2),
                    "from": message.from_agent,
                    "to": message.to_agent,
                    "type": message.message_type.value,
                    "intent": intent,
                    "assignment_id": assignment_id,
                }
            )

            if intent == MessageIntent.ASSIGNMENT_START.value and assignment_id:
                self._assignment_start_ms[assignment_id] = elapsed_ms
                self.mark(
                    f"msg.start.{assignment_id}",
                    agent=message.to_agent,
                    attempt=message.metadata.get("attempt", 0),
                )
            elif intent == MessageIntent.ASSIGNMENT_RESULT.value and assignment_id:
                start = self._assignment_start_ms.get(assignment_id, elapsed_ms)
                duration = elapsed_ms - start
                self._assignment_result_ms[assignment_id] = {
                    "agent": message.from_agent,
                    "duration_ms": round(duration, 2),
                }
                self.mark(
                    f"msg.done.{assignment_id}",
                    agent=message.from_agent,
                    duration_ms=round(duration, 2),
                )
            elif intent == MessageIntent.RETRY_REQUEST.value:
                self.mark("msg.retry_request", from_agent=message.from_agent)

        platform.add_message_listener(on_message)
        self._wrap_llm(platform.llm)

        def unwatch() -> None:
            platform.remove_message_listener(on_message)

        self._unwatch = unwatch

    def detach(self) -> None:
        if self._unwatch:
            self._unwatch()
            self._unwatch = None

    def wrap_agents(self, agents: dict[str, Any]) -> None:
        for agent in agents.values():
            original = agent.think

            async def timed_think(message: Message, _agent=agent, _original=original):
                t0 = time.perf_counter()
                result = await _original(message)
                self.agent_thinks.append(
                    AgentThinkRecord(
                        agent=_agent.name,
                        elapsed_ms=(time.perf_counter() - t0) * 1000,
                        message_type=message.message_type.value,
                        from_agent=message.from_agent,
                    )
                )
                return result

            agent.think = timed_think  # type: ignore[method-assign]

    def _wrap_llm(self, llm) -> None:
        original = llm.chat

        async def timed_chat(
            system_prompt: str,
            user_prompt: str,
            fallback: str = "",
            *,
            role: str = "default",
            **kwargs,
        ):
            t0 = time.perf_counter()
            result = await original(system_prompt, user_prompt, fallback, role=role, **kwargs)
            used_fallback = result == fallback or not llm.available
            self.llm_calls.append(
                LLMCallRecord(
                    elapsed_ms=(time.perf_counter() - t0) * 1000,
                    provider=llm.provider_name,
                    used_fallback=used_fallback,
                    prompt_chars=len(system_prompt) + len(user_prompt),
                )
            )
            return result

        llm.chat = timed_chat  # type: ignore[method-assign]

    async def watch_task(
        self,
        task_store,
        task_id: str,
        *,
        poll_interval: float = 0.05,
        timeout: float = 30.0,
    ) -> TaskStatus | None:
        """Poll task store until terminal status; record assignment transitions."""
        deadline = time.perf_counter() + timeout
        last_status: TaskStatus | None = None

        while time.perf_counter() < deadline:
            task = await task_store.get(task_id)
            if not task:
                await asyncio.sleep(poll_interval)
                continue

            if task.status != last_status:
                status_key = task.status.value
                if status_key not in self._status_seen:
                    self._status_seen.add(status_key)
                    self.mark(f"task.status.{status_key}")
                last_status = task.status

            plan = TaskPlan.from_record(task.plan)
            if plan:
                for assignment in plan.assignments:
                    key = (assignment.id, assignment.status.value)
                    if key in self._assignment_seen:
                        continue
                    self._assignment_seen.add(key)
                    self.mark(
                        f"assignment.{assignment.id}.{assignment.status.value}",
                        agent=assignment.agent,
                        attempt=assignment.attempt,
                    )

            if task.status in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED):
                self.mark(f"task.finished.{task.status.value}")
                return task.status

            await asyncio.sleep(poll_interval)

        self.mark("task.watch_timeout", timeout_s=timeout)
        return last_status

    def summary(self) -> dict[str, Any]:
        total_ms = (time.perf_counter() - self._t0) * 1000 if self.events else 0
        llm_ms = sum(c.elapsed_ms for c in self.llm_calls)
        think_ms = sum(t.elapsed_ms for t in self.agent_thinks)

        by_agent: dict[str, float] = {}
        for record in self.agent_thinks:
            by_agent[record.agent] = by_agent.get(record.agent, 0) + record.elapsed_ms

        assignment_durations: dict[str, float] = {}
        for assignment_id, info in self._assignment_result_ms.items():
            assignment_durations[assignment_id] = info["duration_ms"]

        return {
            "total_ms": round(total_ms, 2),
            "llm_ms": round(llm_ms, 2),
            "llm_pct": round(100 * llm_ms / total_ms, 1) if total_ms else 0,
            "agent_think_ms": round(think_ms, 2),
            "agent_think_pct": round(100 * think_ms / total_ms, 1) if total_ms else 0,
            "overhead_ms": round(max(0, total_ms - llm_ms - think_ms), 2),
            "llm_calls": len(self.llm_calls),
            "messages": len(self.messages),
            "agent_think_by_agent_ms": {k: round(v, 2) for k, v in sorted(by_agent.items())},
            "assignment_wall_ms": {k: round(v, 2) for k, v in sorted(assignment_durations.items())},
            "assignment_agents": {
                k: v["agent"] for k, v in sorted(self._assignment_result_ms.items())
            },
            "events": [
                {
                    "name": e.name,
                    "elapsed_ms": round(e.elapsed_ms, 2),
                    "delta_ms": round(e.delta_ms, 2),
                    **e.metadata,
                }
                for e in self.events
            ],
        }

    def report_text(self) -> str:
        summary = self.summary()
        lines = [
            "Agent Connect — Pipeline Profile",
            "=" * 40,
            f"Total wall time:     {summary['total_ms']:8.1f} ms",
            f"Agent think() sum:   {summary['agent_think_ms']:8.1f} ms  ({summary['agent_think_pct']}%)",
            f"LLM chat() sum:      {summary['llm_ms']:8.1f} ms  ({summary['llm_pct']}%)",
            f"Other / overhead:    {summary['overhead_ms']:8.1f} ms",
            f"Messages observed:   {summary['messages']}",
            f"LLM calls:           {summary['llm_calls']}",
            "",
            "Agent think() by agent:",
        ]
        for agent, ms in summary["agent_think_by_agent_ms"].items():
            lines.append(f"  {agent:12} {ms:8.1f} ms")

        if summary["assignment_wall_ms"]:
            lines.extend(["", "Assignment start→result (from message flow):"])
            agents = summary.get("assignment_agents", {})
            for assignment_id, ms in summary["assignment_wall_ms"].items():
                agent = agents.get(assignment_id, "?")
                lines.append(f"  {assignment_id:6} {agent:12} {ms:8.1f} ms")

        lines.extend(["", "Timeline (delta from previous event):"])
        for event in self.events:
            meta = ", ".join(f"{k}={v}" for k, v in event.metadata.items())
            suffix = f"  ({meta})" if meta else ""
            lines.append(
                f"  {event.elapsed_ms:8.1f} ms  +{event.delta_ms:7.1f} ms  {event.name}{suffix}"
            )

        lines.extend(["", "Interpretation:"])
        if summary["llm_calls"] and summary["llm_pct"] < 5:
            lines.append(
                "  LLM is in fallback mode (no API key) — set OPENAI_API_KEY to measure real model latency."
            )
        if summary["llm_pct"] + summary["agent_think_pct"] > 70:
            lines.append(
                "  Bottleneck is agent/LLM work — Rust on orchestration is unlikely to help much."
            )
        else:
            lines.append(
                "  Orchestration/bus overhead is visible — optimize Python paths before considering Rust."
            )

        return "\n".join(lines)

    def report_json(self) -> str:
        return json.dumps(self.summary(), ensure_ascii=False, indent=2)
