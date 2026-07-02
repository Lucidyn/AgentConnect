"""Task domain detection and multi-domain plan tests."""

import pytest

from backend.core.task_domain import TaskDomain, detect_task_domain


@pytest.mark.parametrize(
    "task,expected",
    [
        ("build a FastAPI health endpoint", TaskDomain.CODING),
        ("write a blog post about AI agents", TaskDomain.WRITING),
        ("analyze competitor pricing strategy", TaskDomain.ANALYSIS),
        ("research papers on transformer architecture", TaskDomain.RESEARCH),
        ("help me organize my week", TaskDomain.GENERAL),
    ],
)
def test_detect_task_domain(task, expected):
    assert detect_task_domain(task) == expected


@pytest.mark.asyncio
async def test_writing_fallback_plan(isolated_paths):
    from backend.agents.analyst import AnalystAgent
    from backend.agents.coder import CoderAgent
    from backend.agents.planner import PlannerAgent
    from backend.agents.research import ResearchAgent
    from backend.agents.reviewer import ReviewerAgent
    from backend.agents.writer import WriterAgent
    from backend.core.llm import LLMClient
    from backend.core.message_bus import InMemoryMessageBus
    from backend.core.registry import AgentRegistry
    from backend.core.services import AgentServices
    from backend.core.shared_memory import InMemorySharedMemory
    from backend.tools.registry import ToolRegistry

    registry = AgentRegistry(isolated_paths["registry"])
    await registry.connect()
    bus = InMemoryMessageBus()
    await bus.connect()
    services = AgentServices(
        bus=bus,
        registry=registry,
        llm=LLMClient(),
        shared_memory=InMemorySharedMemory(),
        tools=ToolRegistry(),
    )
    for cls in (PlannerAgent, ResearchAgent, CoderAgent, WriterAgent, AnalystAgent, ReviewerAgent):
        await cls(services).register()
    planner = PlannerAgent(services)
    data = planner._fallback_plan("写一篇关于多Agent协作的产品文案")

    agents = [a["agent"] for a in data["assignments"]]
    assert "Writer" in agents
    assert "Coder" not in agents
    assert agents[-1] == "Reviewer"

    await bus.disconnect()
    await registry.disconnect()
