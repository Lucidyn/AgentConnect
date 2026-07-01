"""Async database abstraction for TaskStore and MessageOutbox."""

from __future__ import annotations

import logging
import re
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from backend.config import settings

logger = logging.getLogger(__name__)


def _pg_placeholders(sql: str) -> str:
    index = 0

    def repl(_match: re.Match[str]) -> str:
        nonlocal index
        index += 1
        return f"${index}"

    return re.sub(r"\?", repl, sql)


class Database(ABC):
    is_postgres: bool = False

    @abstractmethod
    async def connect(self) -> None: ...

    @abstractmethod
    async def disconnect(self) -> None: ...

    @abstractmethod
    async def execute(self, sql: str, params: tuple[Any, ...] = ()) -> int: ...

    @abstractmethod
    async def fetchone(self, sql: str, params: tuple[Any, ...] = ()) -> tuple | None: ...

    @abstractmethod
    async def fetchall(self, sql: str, params: tuple[Any, ...] = ()) -> list[tuple]: ...

    @abstractmethod
    async def commit(self) -> None: ...

    def adapt(self, sql: str) -> str:
        return sql if not self.is_postgres else _pg_placeholders(sql)


class SQLiteDatabase(Database):
    is_postgres = False

    def __init__(self, path: str) -> None:
        self._path = path
        self._db = None

    @classmethod
    async def open(cls, path: str) -> SQLiteDatabase:
        db = cls(path)
        await db.connect()
        return db

    async def connect(self) -> None:
        import aiosqlite

        from backend.core.sqlite_utils import configure_sqlite

        Path(self._path).parent.mkdir(parents=True, exist_ok=True)
        self._db = await aiosqlite.connect(self._path)
        await configure_sqlite(self._db)

    async def disconnect(self) -> None:
        if self._db:
            await self._db.close()
            self._db = None

    async def execute(self, sql: str, params: tuple[Any, ...] = ()) -> int:
        assert self._db is not None
        cursor = await self._db.execute(sql, params)
        return cursor.rowcount or 0

    async def fetchone(self, sql: str, params: tuple[Any, ...] = ()) -> tuple | None:
        assert self._db is not None
        async with self._db.execute(sql, params) as cursor:
            return await cursor.fetchone()

    async def fetchall(self, sql: str, params: tuple[Any, ...] = ()) -> list[tuple]:
        assert self._db is not None
        async with self._db.execute(sql, params) as cursor:
            return await cursor.fetchall()

    async def commit(self) -> None:
        assert self._db is not None
        await self._db.commit()


class PostgresDatabase(Database):
    is_postgres = True

    def __init__(self, dsn: str) -> None:
        self._dsn = dsn
        self._pool = None

    @classmethod
    async def open(cls, dsn: str) -> PostgresDatabase:
        db = cls(dsn)
        await db.connect()
        return db

    async def connect(self) -> None:
        import asyncpg

        self._pool = await asyncpg.create_pool(
            self._dsn,
            min_size=1,
            max_size=settings.database_pool_size,
        )
        logger.info("PostgreSQL pool connected")

    async def disconnect(self) -> None:
        if self._pool:
            await self._pool.close()
            self._pool = None

    async def execute(self, sql: str, params: tuple[Any, ...] = ()) -> int:
        assert self._pool is not None
        sql = self.adapt(sql)
        async with self._pool.acquire() as conn:
            result = await conn.execute(sql, *params)
        if result.startswith("UPDATE"):
            return int(result.split()[-1])
        return 0

    async def fetchone(self, sql: str, params: tuple[Any, ...] = ()) -> tuple | None:
        assert self._pool is not None
        sql = self.adapt(sql)
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(sql, *params)
        return tuple(row) if row else None

    async def fetchall(self, sql: str, params: tuple[Any, ...] = ()) -> list[tuple]:
        assert self._pool is not None
        sql = self.adapt(sql)
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(sql, *params)
        return [tuple(row) for row in rows]

    async def commit(self) -> None:
        return None


async def create_database(
    *,
    database_url: str | None = None,
    sqlite_path: str | None = None,
) -> Database:
    url = (database_url or settings.database_url or "").strip()
    if url:
        if not url.startswith("postgresql://") and not url.startswith("postgres://"):
            raise ValueError("DATABASE_URL must be a postgresql:// connection string")
        return await PostgresDatabase.open(url)
    path = sqlite_path or settings.tasks_db_path
    return await SQLiteDatabase.open(path)
