"""Fast mode and LLM parameter tests."""

import pytest

from backend.core.fallback_plan import FallbackPlanBuilder
from backend.core.llm_params import llm_params_for_role
from backend.core.plan_dispatch import build_assignment_task
from backend.models.plan import AssignmentStatus, TaskAssignment, TaskPlan
from backend.models.task_context import TaskContext


def test_llm_params_planner_uses_low_temperature():
    params = llm_params_for_role("planner")
    assert params["temperature"] == 0.0
    assert params["max_tokens"] <= 512


def test_build_assignment_task_truncates_long_context(patch_settings):
    patch_settings(assignment_context_max_chars=20)
    plan = TaskPlan(
        assignments=[
            TaskAssignment(id="t1", agent="Research", task="r", status=AssignmentStatus.DONE),
            TaskAssignment(
                id="t2", agent="Coder", task="code", depends_on=["t1"], status=AssignmentStatus.PENDING
            ),
        ]
    )
    ctx = TaskContext(results={"t1": "x" * 100})
    text = build_assignment_task(plan.assignments[1], plan, ctx)
    assert "...(truncated)" in text


@pytest.mark.asyncio
async def test_fast_mode_lite_plan_for_simple_task(isolated_paths, patch_settings):
    from backend.core.message_bus import InMemoryMessageBus
    from backend.core.registry import AgentRegistry
    from backend.core.services import AgentServices
    from backend.core.shared_memory import InMemorySharedMemory
    from backend.tools.registry import ToolRegistry
    from backend.agents.planner import PlannerAgent
    from backend.agents.coder import CoderAgent
    from backend.agents.reviewer import ReviewerAgent
    from backend.core.llm import LLMClient

    patch_settings(fast_mode=True, fast_skip_test_runner=True)

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
    for cls in (PlannerAgent, CoderAgent, ReviewerAgent):
        await cls(services).register()
    planner = PlannerAgent(services)
    data = planner._fallback_plan("build a tiny health API")

    agents = [a["agent"] for a in data["assignments"]]
    assert agents == ["Coder", "Reviewer"]
    assert "TestRunner" not in agents
    assert "Research" not in agents

    await bus.disconnect()
    await registry.disconnect()


@pytest.mark.asyncio
async def test_fast_mode_skips_research_for_generic_task(isolated_paths, patch_settings):
    from backend.core.registry import AgentRegistry
    from backend.agents.planner import PlannerAgent
    from backend.core.message_bus import InMemoryMessageBus
    from backend.core.services import AgentServices
    from backend.core.shared_memory import InMemorySharedMemory
    from backend.core.llm import LLMClient
    from backend.tools.registry import ToolRegistry
    from backend.agents.coder import CoderAgent
    from backend.agents.reviewer import ReviewerAgent
    from backend.agents.research import ResearchAgent
    from backend.agents.test_runner import TestRunnerAgent

    patch_settings(fast_mode=True, fast_skip_research=True, fast_skip_test_runner=True)

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
    for cls in (PlannerAgent, ResearchAgent, CoderAgent, TestRunnerAgent, ReviewerAgent):
        await cls(services).register()
    planner = PlannerAgent(services)
    data = planner._fallback_plan("implement complex distributed system")

    agents = [a["agent"] for a in data["assignments"]]
    assert agents[0] == "Coder"
    assert "Research" not in agents
    assert "TestRunner" not in agents

    await bus.disconnect()
    await registry.disconnect()
