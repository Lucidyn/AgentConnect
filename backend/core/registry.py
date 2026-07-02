"""Agent Registry — registration, discovery, and capability matching."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

import aiosqlite

from backend.config import settings
from backend.core.text_utils import tokenize_set
from backend.models.message import AgentInfo

if TYPE_CHECKING:
    from backend.core.db.base import Database

logger = logging.getLogger(__name__)


class AgentRegistry:
    def __init__(
        self,
        database: Database | None = None,
        db_path: str | None = None,
    ) -> None:
        if isinstance(database, str):
            db_path = database
            database = None
        self._database = database
        self._legacy_path = db_path or settings.registry_db_path
        self._agents: dict[str, AgentInfo] = {}
        self._legacy_db: aiosqlite.Connection | None = None

    async def connect(self) -> None:
        if self._database is not None:
            await self._load_from_db()
            return

        Path(self._legacy_path).parent.mkdir(parents=True, exist_ok=True)
        self._legacy_db = await aiosqlite.connect(self._legacy_path)
        from backend.core.sqlite_utils import configure_sqlite

        await configure_sqlite(self._legacy_db)
        await self._legacy_db.execute(
            """
            CREATE TABLE IF NOT EXISTS agents (
                name TEXT PRIMARY KEY,
                role TEXT NOT NULL,
                capabilities TEXT NOT NULL,
                description TEXT DEFAULT '',
                status TEXT DEFAULT 'idle',
                registered_at TEXT NOT NULL,
                inputs_json TEXT DEFAULT '[]',
                outputs_json TEXT DEFAULT '[]',
                accepts_json TEXT DEFAULT '[]'
            )
            """
        )
        await self._legacy_db.commit()
        await self._load_from_db()

    async def disconnect(self) -> None:
        if self._legacy_db:
            await self._legacy_db.close()
            self._legacy_db = None

    def _row_to_info(self, row: tuple) -> AgentInfo:
        if len(row) >= 9:
            inputs = json.loads(row[6] or "[]")
            outputs = json.loads(row[7] or "[]")
            accepts = json.loads(row[8] or "[]")
        else:
            inputs, outputs, accepts = [], [], []
        registered = row[5]
        if isinstance(registered, datetime):
            registered_at = registered
        else:
            registered_at = datetime.fromisoformat(str(registered))
        return AgentInfo(
            name=row[0],
            role=row[1],
            capabilities=str(row[2]).split(",") if row[2] else [],
            description=row[3] or "",
            status=row[4] or "idle",
            registered_at=registered_at,
            inputs=inputs,
            outputs=outputs,
            accepts=accepts,
        )

    async def _load_from_db(self) -> None:
        sql = (
            "SELECT name, role, capabilities, description, status, registered_at, "
            "inputs_json, outputs_json, accepts_json FROM agents"
        )
        if self._database is not None:
            rows = await self._database.fetchall(sql)
        else:
            assert self._legacy_db is not None
            async with self._legacy_db.execute(sql) as cursor:
                rows = await cursor.fetchall()
        self._agents = {}
        for row in rows:
            info = self._row_to_info(row)
            self._agents[info.name] = info

    async def register(self, info: AgentInfo) -> AgentInfo:
        self._agents[info.name] = info
        registered = info.registered_at
        if registered.tzinfo is None:
            registered = registered.replace(tzinfo=timezone.utc)
        params = (
            info.name,
            info.role,
            ",".join(info.capabilities),
            info.description,
            info.status,
            registered if self._database and self._database.is_postgres else registered.isoformat(),
            json.dumps(info.inputs or [], ensure_ascii=False),
            json.dumps(info.outputs or [], ensure_ascii=False),
            json.dumps(info.accepts or [], ensure_ascii=False),
        )
        if self._database is not None:
            if self._database.is_postgres:
                sql = """
                INSERT INTO agents
                    (name, role, capabilities, description, status, registered_at,
                     inputs_json, outputs_json, accepts_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (name) DO UPDATE SET
                    role = EXCLUDED.role,
                    capabilities = EXCLUDED.capabilities,
                    description = EXCLUDED.description,
                    status = EXCLUDED.status,
                    registered_at = EXCLUDED.registered_at,
                    inputs_json = EXCLUDED.inputs_json,
                    outputs_json = EXCLUDED.outputs_json,
                    accepts_json = EXCLUDED.accepts_json
                """
            else:
                sql = """
                INSERT OR REPLACE INTO agents
                    (name, role, capabilities, description, status, registered_at,
                     inputs_json, outputs_json, accepts_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """
            await self._database.execute(sql, params)
            await self._database.commit()
        else:
            assert self._legacy_db is not None
            await self._legacy_db.execute(
                """
                INSERT OR REPLACE INTO agents
                    (name, role, capabilities, description, status, registered_at,
                     inputs_json, outputs_json, accepts_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                params,
            )
            await self._legacy_db.commit()
        logger.info("Registered agent: %s (%s)", info.name, info.role)
        return info

    async def unregister(self, name: str) -> None:
        self._agents.pop(name, None)
        if self._database is not None:
            await self._database.execute("DELETE FROM agents WHERE name = ?", (name,))
            await self._database.commit()
        elif self._legacy_db:
            await self._legacy_db.execute("DELETE FROM agents WHERE name = ?", (name,))
            await self._legacy_db.commit()

    async def update_status(self, name: str, status: str) -> None:
        if name in self._agents:
            self._agents[name].status = status
            if self._database is not None:
                await self._database.execute(
                    "UPDATE agents SET status = ? WHERE name = ?",
                    (status, name),
                )
                await self._database.commit()
            elif self._legacy_db:
                await self._legacy_db.execute(
                    "UPDATE agents SET status = ? WHERE name = ?",
                    (status, name),
                )
                await self._legacy_db.commit()

    def get(self, name: str) -> AgentInfo | None:
        return self._agents.get(name)

    def list_agents(self) -> list[AgentInfo]:
        return list(self._agents.values())

    def find_by_capability(self, capability: str) -> list[AgentInfo]:
        cap = capability.lower()
        return [
            agent
            for agent in self._agents.values()
            if any(cap in c.lower() for c in agent.capabilities)
        ]

    def discover(self, query: str, limit: int = 5) -> list[tuple[AgentInfo, float]]:
        """Score agents by relevance to a natural-language query."""
        query_tokens = tokenize_set(query)
        if not query_tokens:
            return []

        scored: list[tuple[AgentInfo, float]] = []
        for agent in self._agents.values():
            score = 0.0
            agent_tokens = tokenize_set(
                f"{agent.name} {agent.role} {agent.description} {' '.join(agent.capabilities)}"
            )
            overlap = query_tokens & agent_tokens
            score += len(overlap) * 2.0

            for cap in agent.capabilities:
                cap_lower = cap.lower()
                if cap_lower in query.lower():
                    score += 3.0

            if agent.name.lower() in query.lower():
                score += 5.0

            if score > 0:
                scored.append((agent, score))

        scored.sort(key=lambda item: item[1], reverse=True)
        return scored[:limit]

    def best_for_task(self, task: str) -> AgentInfo | None:
        results = self.discover(task, limit=1)
        return results[0][0] if results else None

    def catalog_for_planner(self) -> str:
        lines = []
        for agent in self.list_agents():
            caps = ", ".join(agent.capabilities)
            contract = []
            if agent.inputs:
                contract.append(f"inputs={','.join(agent.inputs)}")
            if agent.outputs:
                contract.append(f"outputs={','.join(agent.outputs)}")
            if agent.accepts:
                contract.append(f"accepts={','.join(agent.accepts)}")
            suffix = f" ({'; '.join(contract)})" if contract else ""
            lines.append(f"- {agent.name} ({agent.role}): {agent.description} [{caps}]{suffix}")
        return "\n".join(lines)
