"""Structured trace logging — JSON events keyed by task_id."""

from __future__ import annotations

import json
import logging
from typing import Any


def log_event(logger: logging.Logger, event: str, **fields: Any) -> None:
    payload = {"event": event, **{k: v for k, v in fields.items() if v is not None and v != ""}}
    logger.info(json.dumps(payload, ensure_ascii=False, default=str))
