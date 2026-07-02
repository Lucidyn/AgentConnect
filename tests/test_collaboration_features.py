"""Collaboration protocol, artifacts, contracts, and tester agent tests."""

import pytest

from backend.agents.test_runner import TestRunnerAgent
from backend.core.task_store import TaskStore
from backend.models.artifact import Artifact
from backend.models.message import Message, MessageIntent, MessageType
from backend.models.plan import TaskPlan


def test_message_thread_and_quality_fields():
    msg = Message(
        from_agent="Coder",
        to_agent="Research",
        content="question",
        message_type=MessageType.TASK,
        task_id="task-1",
        metadata={"reply_to": "parent-1"},
        priority=5,
        requires_response=True,
        expected_response_type="research_report",
    ).with_trace()

    assert msg.thread_id == "task-1"
    assert msg.parent_message_id == "parent-1"
    assert msg.priority == 5
    assert msg.requires_response is True
    assert msg.expected_response_type == "research_report"


@pytest.mark.asyncio
async def test_artifact_store_roundtrip(db_path):
    store = TaskStore(db_path)
    await store.connect()

    artifact = await store.save_artifact(
        Artifact(
            task_id="task-1",
            assignment_id="t2",
            type="code_patch",
            content={"summary": "hello"},
            metadata={"attempt": 1},
            created_by="Coder",
        )
    )

    loaded = await store.get_artifact(artifact.id)
    assert loaded is not None
    assert loaded.content["summary"] == "hello"
    assert loaded.metadata["attempt"] == 1

    artifacts = await store.list_artifacts("task-1")
    assert [a.id for a in artifacts] == [artifact.id]

    await store.disconnect()


@pytest.mark.asyncio
async def test_registry_catalog_includes_agent_contract(isolated_paths):
    from backend.agents.coder import CoderAgent
    from backend.core.message_bus import InMemoryMessageBus
    from backend.core.registry import AgentRegistry
    from backend.core.services import AgentServices
    from backend.core.shared_memory import InMemorySharedMemory
    from backend.core.llm import LLMClient
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

    coder = CoderAgent(services)
    await coder.register()

    catalog = registry.catalog_for_planner()
    assert "inputs=research_report,review_feedback,test_result" in catalog
    assert "outputs=code_patch,implementation_notes" in catalog

    await bus.disconnect()
    await registry.disconnect()


def test_test_runner_reports_pass_and_retry_intent():
    from backend.agents.test_runner import TestRunnerAgent, is_test_failed

    passed = TestRunnerAgent._mock_test("from fastapi import FastAPI\n@app.get('/health')\ndef h(): pass")
    failed = TestRunnerAgent._mock_test("from fastapi import FastAPI\napp = FastAPI()")

    assert "【测试结果】通过" in passed
    assert is_test_failed(failed)
    assert not is_test_failed(passed)


def test_test_runner_python_syntax_validation():
    from backend.agents.test_runner import TestRunnerAgent, is_test_failed

    bad = TestRunnerAgent._run_validation("```python\ndef broken(:\n    pass\n```")
    assert is_test_failed(bad)
    assert "SyntaxError" in bad

    good = TestRunnerAgent._run_validation("```python\ndef ok():\n    return 1\n```")
    assert not is_test_failed(good)


@pytest.mark.asyncio
async def test_fallback_plan_includes_reasons_and_tester(isolated_paths):
    from backend.agents.coder import CoderAgent
    from backend.agents.planner import PlannerAgent
    from backend.agents.research import ResearchAgent
    from backend.agents.reviewer import ReviewerAgent
    from backend.agents.test_runner import TestRunnerAgent
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
    for cls in (PlannerAgent, ResearchAgent, CoderAgent, TestRunnerAgent, ReviewerAgent):
        await cls(services).register()
    planner = PlannerAgent(services)
    data = planner._fallback_plan("build API")

    assignments = data["assignments"]
    assert any(a["agent"] == "TestRunner" for a in assignments)
    assert all(a.get("reason") for a in assignments)

    await bus.disconnect()
    await registry.disconnect()
