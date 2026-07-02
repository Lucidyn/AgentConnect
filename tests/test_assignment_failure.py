"""Assignment failure handling and plan recovery tests."""

import asyncio

import pytest

from backend.core.task_store import TaskStore
from backend.models.message import Message, MessageType
from backend.models.plan import AssignmentStatus, TaskAssignment, TaskPlan
from backend.models.task import TaskStatus
from backend.models.task_context import TaskContext


@pytest.mark.asyncio
async def test_reset_running_to_pending():
    plan = TaskPlan(
        assignments=[
            TaskAssignment(id="t1", agent="Research", task="a", status=AssignmentStatus.DONE),
            TaskAssignment(id="t2", agent="Coder", task="b", status=AssignmentStatus.RUNNING),
            TaskAssignment(id="t3", agent="Reviewer", task="c", status=AssignmentStatus.PENDING),
        ]
    )
    assert plan.reset_running_to_pending() == 1
    assert plan.assignments[1].status == AssignmentStatus.PENDING
    assert plan.assignments[0].status == AssignmentStatus.DONE


@pytest.mark.asyncio
async def test_recover_stale_resets_running_assignments(db_path):
    store = TaskStore(db_path)
    await store.connect()

    task = await store.create("with plan", status=TaskStatus.RUNNING)
    plan = TaskPlan(
        assignments=[
            TaskAssignment(id="t1", agent="Research", task="a", status=AssignmentStatus.DONE),
            TaskAssignment(id="t2", agent="Coder", task="b", status=AssignmentStatus.RUNNING),
        ]
    )
    await store.save_plan(task.id, plan.to_context())

    await store.recover_stale_tasks()

    recovered = await store.get(task.id)
    assert recovered.status == TaskStatus.QUEUED
    reloaded = TaskContext.plan_from_record(recovered.plan)
    assert reloaded.assignments[1].status == AssignmentStatus.PENDING

    await store.disconnect()


@pytest.mark.asyncio
async def test_planner_retries_then_fails_assignment(isolated_paths, patch_settings):
    from backend.agents.planner import PlannerAgent
    from backend.constants import PLANNER
    from backend.core.llm import LLMClient
    from backend.core.message_bus import InMemoryMessageBus
    from backend.core.registry import AgentRegistry
    from backend.core.services import AgentServices
    from backend.core.shared_memory import InMemorySharedMemory
    from backend.core.task_store import TaskStore
    from backend.tools.registry import ToolRegistry

    patch_settings(assignment_max_retries=1, enabled_agents="planner")

    registry = AgentRegistry(isolated_paths["registry"])
    await registry.connect()
    store = TaskStore(isolated_paths["tasks"])
    await store.connect()
    task = await store.create("retry test", status=TaskStatus.RUNNING)

    plan = TaskPlan(
        summary="test",
        assignments=[
            TaskAssignment(id="t1", agent="Flaky", task="work", status=AssignmentStatus.RUNNING),
        ],
    )
    await store.save_plan(task.id, plan.to_context())

    bus = InMemoryMessageBus()
    await bus.connect()
    services = AgentServices(
        bus=bus,
        registry=registry,
        llm=LLMClient(),
        shared_memory=InMemorySharedMemory(),
        tools=ToolRegistry(),
        task_store=store,
    )
    planner = PlannerAgent(services)
    await planner.register()
    await planner.start()

    def error_msg() -> Message:
        return Message(
            from_agent="Flaky",
            to_agent=PLANNER,
            content="Error: boom",
            message_type=MessageType.ERROR,
            task_id=task.id,
            metadata={"assignment_id": "t1"},
        ).with_trace()

    await bus.publish(error_msg())
    await asyncio.sleep(0.15)

    mid = await store.get(task.id)
    reloaded = TaskContext.plan_from_record(mid.plan)
    assert reloaded.assignments[0].status == AssignmentStatus.RUNNING
    ctx = TaskContext.model_validate(mid.context or {})
    assert ctx.assignment_retries.get("t1") == 1

    await bus.publish(error_msg())
    await asyncio.sleep(0.15)

    final = await store.get(task.id)
    assert final.status == TaskStatus.FAILED
    reloaded = TaskContext.plan_from_record(final.plan)
    assert reloaded.assignments[0].status == AssignmentStatus.FAILED

    await planner.stop()
    await bus.disconnect()
    await store.disconnect()
    await registry.disconnect()


@pytest.mark.asyncio
async def test_planner_resumes_existing_plan(isolated_paths, patch_settings):
    from backend.agents.planner import PlannerAgent
    from backend.core.llm import LLMClient
    from backend.core.message_bus import InMemoryMessageBus
    from backend.core.registry import AgentRegistry
    from backend.core.services import AgentServices
    from backend.core.shared_memory import InMemorySharedMemory
    from backend.core.task_store import TaskStore
    from backend.tools.registry import ToolRegistry

    patch_settings(enabled_agents="planner,research,coder,reviewer")

    registry = AgentRegistry(isolated_paths["registry"])
    await registry.connect()
    store = TaskStore(isolated_paths["tasks"])
    await store.connect()
    task = await store.create("resume me", status=TaskStatus.QUEUED)

    plan = TaskPlan(
        summary="partial",
        assignments=[
            TaskAssignment(id="t1", agent="Research", task="a", status=AssignmentStatus.DONE),
            TaskAssignment(id="t2", agent="Coder", task="b", status=AssignmentStatus.PENDING, depends_on=["t1"]),
        ],
    )
    await store.save_plan(task.id, plan.to_context())

    bus = InMemoryMessageBus()
    await bus.connect()
    services = AgentServices(
        bus=bus,
        registry=registry,
        llm=LLMClient(),
        shared_memory=InMemorySharedMemory(),
        tools=ToolRegistry(),
        task_store=store,
    )
    planner = PlannerAgent(services)
    await planner.register()
    await planner.start()

    user_msg = Message(
        from_agent="User",
        to_agent="Planner",
        content=task.input,
        message_type=MessageType.TASK,
        task_id=task.id,
    ).with_trace()
    await bus.publish(user_msg)
    await asyncio.sleep(0.2)

    reloaded = TaskContext.plan_from_record((await store.get(task.id)).plan)
    assert reloaded.assignments[1].status == AssignmentStatus.RUNNING
    assert reloaded.summary == "partial"

    await planner.stop()
    await bus.disconnect()
    await store.disconnect()
    await registry.disconnect()
