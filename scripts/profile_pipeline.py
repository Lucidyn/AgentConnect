#!/usr/bin/env python3
"""Profile an end-to-end Agent Connect pipeline run and print a timing breakdown.

Usage:
  python scripts/profile_pipeline.py
  python scripts/profile_pipeline.py --task "build OCR service" --repeat 3
  python scripts/profile_pipeline.py --json
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.config import settings
from backend.core.profiling import PipelineProfiler
from backend.models.task import TaskStatus
from backend.platform import Platform
from backend.tools.base import ToolResult
from backend.tools.registry import ToolRegistry


async def _mock_run_for_task(self, task: str) -> list[ToolResult]:
    return [ToolResult("mock", True, f"mock research for {task[:40]}")]


async def run_once(task_input: str, *, use_temp_db: bool, fast_mode: bool) -> PipelineProfiler:
    if use_temp_db:
        tmp = tempfile.mkdtemp(prefix="agent_connect_profile_")
        settings.tasks_db_path = str(Path(tmp) / "tasks.db")
        settings.registry_db_path = str(Path(tmp) / "registry.db")

    settings.use_redis = False
    settings.use_qdrant = False
    settings.message_reliability = True
    settings.max_concurrent_tasks = 1
    if fast_mode:
        settings.fast_mode = True
        settings.fast_skip_planner_llm = True
        settings.fast_skip_research = True
        settings.fast_skip_test_runner = True

    ToolRegistry.run_for_task = _mock_run_for_task  # type: ignore[method-assign]

    profiler = PipelineProfiler()
    platform = Platform()

    profiler.mark("platform.start")
    await platform.start()
    profiler.mark("platform.ready")
    profiler.attach_platform(platform)
    profiler.wrap_agents(platform.agents)

    task, message = await platform.submit_task(task_input)
    profiler.mark("task.submitted", task_id=task.id)

    if message is None:
        profiler.mark("task.queued")
    else:
        profiler.mark("task.dispatched")

    final_status = await profiler.watch_task(platform.task_store, task.id)
    profiler.mark("platform.stop")
    profiler.detach()
    await platform.stop()

    if final_status != TaskStatus.COMPLETED:
        profiler.mark("task.incomplete", status=final_status.value if final_status else "unknown")

    return profiler


async def main() -> int:
    parser = argparse.ArgumentParser(description="Profile Agent Connect E2E pipeline timing")
    parser.add_argument(
        "--task",
        default="build a tiny health API",
        help="User task submitted to the platform",
    )
    parser.add_argument("--repeat", type=int, default=1, help="Number of runs to average")
    parser.add_argument("--json", action="store_true", help="Output JSON instead of text report")
    parser.add_argument(
        "--keep-db",
        action="store_true",
        help="Use configured DB paths instead of temp files",
    )
    parser.add_argument(
        "--fast",
        action="store_true",
        help="Enable fast_mode (skip Planner LLM, Research, TestRunner)",
    )
    args = parser.parse_args()

    profilers: list[PipelineProfiler] = []
    for i in range(args.repeat):
        if args.repeat > 1:
            print(f"Run {i + 1}/{args.repeat}...", file=sys.stderr)
        profilers.append(await run_once(args.task, use_temp_db=not args.keep_db, fast_mode=args.fast))

    profiler = profilers[-1]
    if args.repeat > 1:
        totals = [p.summary()["total_ms"] for p in profilers]
        avg = sum(totals) / len(totals)
        print(f"\nAverage total over {args.repeat} runs: {avg:.1f} ms\n", file=sys.stderr)

    if args.json:
        print(profiler.report_json())
    else:
        print(profiler.report_text())

    last = profilers[-1].summary()
    return 0 if last.get("events") and "task.finished.completed" in {e["name"] for e in last["events"]} else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
