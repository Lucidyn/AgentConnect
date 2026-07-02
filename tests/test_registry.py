"""Registry discovery tests."""

import pytest

from backend.core.registry import AgentRegistry
from backend.models.message import AgentInfo


@pytest.mark.asyncio
async def test_discover_matches_capabilities(db_path):
    registry = AgentRegistry(db_path)
    await registry.connect()

    await registry.register(
        AgentInfo(
            name="Research",
            role="researcher",
            capabilities=["arxiv", "paper_lookup", "search"],
            description="paper research",
        )
    )
    await registry.register(
        AgentInfo(
            name="Coder",
            role="developer",
            capabilities=["coding", "python"],
            description="writes code",
        )
    )

    results = registry.discover("arxiv paper research", limit=2)
    assert results
    assert results[0][0].name == "Research"

    await registry.disconnect()
