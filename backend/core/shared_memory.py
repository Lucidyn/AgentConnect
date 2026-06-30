"""Shared memory — vector store for cross-agent knowledge (Qdrant with fallback)."""

from __future__ import annotations

import logging
import math
from abc import ABC, abstractmethod
from collections import Counter
from typing import Callable

from backend.config import settings
from backend.core.text_utils import tokenize_words
from backend.models.memory import MemoryEntry

logger = logging.getLogger(__name__)

COLLECTION = "agent_memory"
VECTOR_SIZE = 384


def _embed_text(text: str) -> list[float]:
    tokens = tokenize_words(text)
    if not tokens:
        return [0.0] * VECTOR_SIZE

    counts = Counter(tokens)
    vec = [0.0] * VECTOR_SIZE
    for token, count in counts.items():
        idx = hash(token) % VECTOR_SIZE
        vec[idx] += count
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


def _cosine(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


class SharedMemory(ABC):
    @abstractmethod
    async def connect(self) -> None: ...

    @abstractmethod
    async def disconnect(self) -> None: ...

    @abstractmethod
    async def store(
        self,
        content: str,
        agent: str,
        metadata: dict | None = None,
        task_id: str = "",
    ) -> str: ...

    @abstractmethod
    async def query(self, query: str, limit: int = 5, task_id: str = "") -> list[MemoryEntry]: ...


class InMemorySharedMemory(SharedMemory):
    def __init__(self) -> None:
        self._entries: list[MemoryEntry] = []
        self._vectors: list[list[float]] = []

    async def connect(self) -> None:
        logger.info("In-memory shared memory ready")

    async def disconnect(self) -> None:
        self._entries.clear()
        self._vectors.clear()

    async def store(
        self,
        content: str,
        agent: str,
        metadata: dict | None = None,
        task_id: str = "",
    ) -> str:
        meta = dict(metadata or {})
        if task_id:
            meta["task_id"] = task_id
        entry = MemoryEntry(agent=agent, content=content, metadata=meta)
        self._entries.append(entry)
        self._vectors.append(_embed_text(content))
        return entry.id

    async def query(self, query: str, limit: int = 5, task_id: str = "") -> list[MemoryEntry]:
        if not self._entries:
            return []

        entries = self._entries
        vectors = self._vectors
        if task_id:
            filtered = [
                (e, v) for e, v in zip(entries, vectors) if e.metadata.get("task_id") == task_id
            ]
            if not filtered:
                return []
            entries, vectors = zip(*filtered)
        query_vec = _embed_text(query)
        scored = [
            (entry, _cosine(query_vec, vec))
            for entry, vec in zip(entries, vectors)
        ]
        scored.sort(key=lambda item: item[1], reverse=True)
        results: list[MemoryEntry] = []
        for entry, score in scored[:limit]:
            copy = entry.model_copy()
            copy.score = score
            results.append(copy)
        return results


class QdrantSharedMemory(SharedMemory):
    def __init__(self, path: str, embed: Callable[[str], list[float]] = _embed_text) -> None:
        self._path = path
        self._embed = embed
        self._client = None

    async def connect(self) -> None:
        from qdrant_client import QdrantClient
        from qdrant_client.models import Distance, VectorParams

        self._client = QdrantClient(path=self._path)
        if not self._client.collection_exists(COLLECTION):
            self._client.create_collection(
                collection_name=COLLECTION,
                vectors_config=VectorParams(size=VECTOR_SIZE, distance=Distance.COSINE),
            )
        logger.info("Qdrant shared memory ready at %s", self._path)

    async def disconnect(self) -> None:
        if self._client:
            self._client.close()
            self._client = None

    async def store(
        self,
        content: str,
        agent: str,
        metadata: dict | None = None,
        task_id: str = "",
    ) -> str:
        from qdrant_client.models import PointStruct

        meta = dict(metadata or {})
        if task_id:
            meta["task_id"] = task_id
        entry = MemoryEntry(agent=agent, content=content, metadata=meta)
        vector = self._embed(content)
        assert self._client is not None
        self._client.upsert(
            collection_name=COLLECTION,
            points=[PointStruct(id=entry.id, vector=vector, payload=entry.model_dump(mode="json"))],
        )
        return entry.id

    async def query(self, query: str, limit: int = 5, task_id: str = "") -> list[MemoryEntry]:
        from qdrant_client.models import FieldCondition, Filter, MatchValue

        assert self._client is not None
        query_filter = None
        if task_id:
            query_filter = Filter(
                must=[FieldCondition(key="metadata.task_id", match=MatchValue(value=task_id))]
            )
        hits = self._client.query_points(
            collection_name=COLLECTION,
            query=self._embed(query),
            query_filter=query_filter,
            limit=limit,
        ).points
        results: list[MemoryEntry] = []
        for hit in hits:
            entry = MemoryEntry.model_validate(hit.payload)
            entry.score = hit.score or 0.0
            results.append(entry)
        return results


async def create_shared_memory() -> SharedMemory:
    if settings.use_qdrant:
        try:
            from pathlib import Path

            Path(settings.qdrant_path).parent.mkdir(parents=True, exist_ok=True)
            store = QdrantSharedMemory(settings.qdrant_path)
            await store.connect()
            return store
        except Exception as exc:
            logger.warning("Qdrant unavailable (%s), falling back to in-memory store", exc)

    store = InMemorySharedMemory()
    await store.connect()
    return store
