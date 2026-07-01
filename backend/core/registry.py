"""Agent Registry — registration, discovery, and capability matching."""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

import aiosqlite

from backend.config import settings
from backend.core.text_utils import tokenize_set
from backend.models.message import AgentInfo

logger = logging.getLogger(__name__)


class AgentRegistry:
    def __init__(self, db_path: str | None = None) -> None:
        self._db_path = db_path or settings.registry_db_path
        self._agents: dict[str, AgentInfo] = {}
        self._db: aiosqlite.Connection | None = None

    async def connect(self) -> None:
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        self._db = await aiosqlite.connect(self._db_path)
        from backend.core.sqlite_utils import configure_sqlite

        await configure_sqlite(self._db)
        await self._db.execute(
            """
            CREATE TABLE IF NOT EXISTS agents (
                name TEXT PRIMARY KEY,
                role TEXT NOT NULL,
                capabilities TEXT NOT NULL,
                description TEXT DEFAULT '',
                status TEXT DEFAULT 'idle',
                registered_at TEXT NOT NULL
            )
            """
        )
        await self._db.commit()
        await self._load_from_db()

    async def disconnect(self) -> None:
        if self._db:
            await self._db.close()

    async def _load_from_db(self) -> None:
        assert self._db is not None
        async with self._db.execute("SELECT * FROM agents") as cursor:
            rows = await cursor.fetchall()
            for row in rows:
                info = AgentInfo(
                    name=row[0],
                    role=row[1],
                    capabilities=row[2].split(","),
                    description=row[3],
                    status=row[4],
                    registered_at=datetime.fromisoformat(row[5]),
                )
                self._agents[info.name] = info

    async def register(self, info: AgentInfo) -> AgentInfo:
        self._agents[info.name] = info
        assert self._db is not None
        await self._db.execute(
            """
            INSERT OR REPLACE INTO agents (name, role, capabilities, description, status, registered_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                info.name,
                info.role,
                ",".join(info.capabilities),
                info.description,
                info.status,
                info.registered_at.isoformat(),
            ),
        )
        await self._db.commit()
        logger.info("Registered agent: %s (%s)", info.name, info.role)
        return info

    async def unregister(self, name: str) -> None:
        self._agents.pop(name, None)
        if self._db:
            await self._db.execute("DELETE FROM agents WHERE name = ?", (name,))
            await self._db.commit()

    async def update_status(self, name: str, status: str) -> None:
        if name in self._agents:
            self._agents[name].status = status
            if self._db:
                await self._db.execute(
                    "UPDATE agents SET status = ? WHERE name = ?",
                    (status, name),
                )
                await self._db.commit()

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
