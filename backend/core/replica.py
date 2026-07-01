"""API replica identity for horizontal scaling."""

from __future__ import annotations

import os
import socket
from uuid import uuid4

from backend.config import settings

_replica_id: str | None = None


def get_replica_id() -> str:
    global _replica_id
    if _replica_id is not None:
        return _replica_id
    env_id = (os.environ.get("API_REPLICA_ID") or settings.api_replica_id or "").strip()
    _replica_id = env_id or f"{socket.gethostname()}-{uuid4().hex[:8]}"
    return _replica_id


def reset_replica_id_for_tests() -> None:
    global _replica_id
    _replica_id = None
