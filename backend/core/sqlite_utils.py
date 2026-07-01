"""SQLite connection helpers."""

from __future__ import annotations

import aiosqlite


async def configure_sqlite(db: aiosqlite.Connection) -> None:
    """Enable WAL mode for better read/write concurrency."""
    await db.execute("PRAGMA journal_mode=WAL")
    await db.execute("PRAGMA synchronous=NORMAL")
    await db.execute("PRAGMA foreign_keys=ON")
