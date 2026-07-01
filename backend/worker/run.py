"""Distributed worker entry — consume assignments from Redis Stream."""

from __future__ import annotations

import asyncio
import logging
import sys

from backend.config import settings
from backend.worker.platform import WorkerPlatform

logger = logging.getLogger(__name__)


async def run_worker() -> None:
    agent_name = (settings.worker_agent_name or "").strip()
    if not agent_name:
        print("WORKER_AGENT_NAME is required (e.g. Research, Coder, Writer).", file=sys.stderr)
        sys.exit(1)

    platform = WorkerPlatform(agent_name)
    await platform.start()
    try:
        await platform.run_loop()
    finally:
        await platform.stop()


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    if not settings.worker_mode:
        print("Set WORKER_MODE=true to start a worker process.")
        print("Example: WORKER_MODE=true WORKER_AGENT_NAME=Coder python -m backend.worker.run")
        return
    asyncio.run(run_worker())


if __name__ == "__main__":
    main()
