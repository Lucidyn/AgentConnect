"""Phase 3 worker entry — consumes assignment envelopes (stub stream consumer)."""

from __future__ import annotations

import asyncio
import logging

from backend.config import settings

logger = logging.getLogger(__name__)


async def run_worker_loop() -> None:
    """Poll worker stream when WORKER_MODE is enabled (Phase 3 scaffold)."""
    stream = settings.worker_stream_key
    logger.info(
        "Worker mode enabled — listening on stream '%s' (stub; assignments still in-process)",
        stream,
    )
    while True:
        await asyncio.sleep(settings.worker_poll_interval)


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    if not settings.worker_mode:
        print("Set WORKER_MODE=true to start the worker process.")
        return
    asyncio.run(run_worker_loop())


if __name__ == "__main__":
    main()
