"""Plan validation, dispatch context, and reviewer retry via Planner."""

import asyncio

import pytest

from backend.core.plan_dispatch import build_assignment_task
from backend.core.plan_validate import validate_assignments
from backend.models.plan import AssignmentStatus, TaskAssignment, TaskPlan
from backend.models.task_context import TaskContext


def test_validate_rejects_duplicate_ids():
    assignments = [
        TaskAssignment(id="t1", agent="A", task="a"),
        TaskAssignment(id="t1", agent="B", task="b"),
    ]
    errors = validate_assignments(assignments)
    assert any("duplicate" in e for e in errors)


def test_validate_rejects_unknown_dependency():
    assignments = [
        TaskAssignment(id="t1", agent="A", task="a", depends_on=["missing"]),
    ]
    errors = validate_assignments(assignments)
    assert any("unknown id" in e for e in errors)


def test_validate_rejects_cycle():
    assignments = [
        TaskAssignment(id="t1", agent="A", task="a", depends_on=["t2"]),
        TaskAssignment(id="t2", agent="B", task="b", depends_on=["t1"]),
    ]
    errors = validate_assignments(assignments)
    assert any("cycle" in e for e in errors)


def test_build_assignment_task_injects_dependencies():
    plan = TaskPlan(
        assignments=[
            TaskAssignment(id="t1", agent="Research", task="调研", status=AssignmentStatus.DONE),
            TaskAssignment(
                id="t2", agent="Coder", task="实现", depends_on=["t1"], status=AssignmentStatus.PENDING
            ),
        ]
    )
    ctx = TaskContext(results={"t1": "research output"})
    coder_asg = plan.assignments[1]
    text = build_assignment_task(coder_asg, plan, ctx)
    assert "实现" in text
    assert "[Research]" in text
    assert "research output" in text


def test_build_assignment_task_reviewer_prefix():
    plan = TaskPlan(
        assignments=[
            TaskAssignment(id="t1", agent="Coder", task="code", status=AssignmentStatus.DONE),
            TaskAssignment(
                id="t2", agent="Reviewer", task="审查", depends_on=["t1"], status=AssignmentStatus.PENDING
            ),
        ]
    )
    ctx = TaskContext(results={"t1": "def app(): pass"})
    text = build_assignment_task(plan.assignments[1], plan, ctx)
    assert text.startswith("请审查以下内容")


@pytest.mark.asyncio
async def test_parse_plan_rejects_invalid_llm_plan(isolated_paths, patch_settings):
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

    invalid = '{"summary":"bad","assignments":[{"id":"t1","agent":"Coder","task":"x","depends_on":["t2"]},{"id":"t2","agent":"Research","task":"y","depends_on":["t1"]}]}'
    plan = planner._parse_plan(invalid, "test task", planner._fallback_plan("test task"))
    errors = plan.validate()
    assert errors == []

    await bus.disconnect()
    await store.disconnect()
    await registry.disconnect()


@pytest.mark.asyncio
async def test_reviewer_retry_goes_through_planner(isolated_paths, patch_settings):
    from backend.agents.planner import PlannerAgent
    from backend.constants import PLANNER, REVIEWER
    from backend.core.llm import LLMClient
    from backend.core.message_bus import InMemoryMessageBus
    from backend.core.registry import AgentRegistry
    from backend.core.services import AgentServices
    from backend.core.shared_memory import InMemorySharedMemory
    from backend.core.task_store import TaskStore
    from backend.models.message import Message, MessageType
    from backend.models.task import TaskStatus
    from backend.tools.registry import ToolRegistry

    patch_settings(enabled_agents="planner,research,coder,reviewer")

    registry = AgentRegistry(isolated_paths["registry"])
    await registry.connect()
    store = TaskStore(isolated_paths["tasks"])
    await store.connect()
    task = await store.create("review retry", status=TaskStatus.RUNNING)

    plan = TaskPlan(
        summary="pipe",
        assignments=[
            TaskAssignment(id="t1", agent="Research", task="a", status=AssignmentStatus.DONE),
            TaskAssignment(id="t2", agent="Coder", task="b", status=AssignmentStatus.DONE, depends_on=["t1"]),
            TaskAssignment(
                id="t3", agent="Reviewer", task="c", status=AssignmentStatus.RUNNING, depends_on=["t2"]
            ),
        ],
    )
    await store.save_plan(task.id, plan.to_context())
    ctx = TaskContext(results={"t1": "r", "t2": "bad code"}, coder_result="bad code")
    await store.save_context(task.id, ctx.model_dump())

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

    retry_msg = Message(
        from_agent=REVIEWER,
        to_agent=PLANNER,
        content="审查发现问题，请修改：缺少异常处理",
        message_type=MessageType.RESPONSE,
        task_id=task.id,
        metadata={"needs_retry": True, "assignment_id": "t3"},
    ).with_trace()

    await bus.publish(retry_msg)
    await asyncio.sleep(0.2)

    reloaded = TaskContext.plan_from_record((await store.get(task.id)).plan)
    coder = reloaded.find_assignment(assignment_id="t2")
    assert coder.status == AssignmentStatus.RUNNING
    reviewer = reloaded.find_assignment(assignment_id="t3")
    assert reviewer.status == AssignmentStatus.PENDING

    saved_ctx = TaskContext.model_validate((await store.get(task.id)).context or {})
    assert "缺少异常处理" in saved_ctx.retry_feedback

    await planner.stop()
    await bus.disconnect()
    await store.disconnect()
    await registry.disconnect()


@pytest.mark.asyncio
async def test_reviewer_loop_enters_approval_after_max_iterations(
    isolated_paths, patch_settings
):
    from backend.agents.planner import PlannerAgent
    from backend.constants import PLANNER, REVIEWER
    from backend.core.llm import LLMClient
    from backend.core.message_bus import InMemoryMessageBus
    from backend.core.registry import AgentRegistry
    from backend.core.services import AgentServices
    from backend.core.shared_memory import InMemorySharedMemory
    from backend.core.task_store import TaskStore
    from backend.models.message import Message, MessageType
    from backend.models.task import TaskStatus
    from backend.tools.registry import ToolRegistry

    patch_settings(enabled_agents="planner,research,coder,reviewer", loop_max_iterations=1)

    registry = AgentRegistry(isolated_paths["registry"])
    await registry.connect()
    store = TaskStore(isolated_paths["tasks"])
    await store.connect()
    task = await store.create("review loop", status=TaskStatus.RUNNING)

    plan = TaskPlan(
        summary="pipe",
        assignments=[
            TaskAssignment(id="t1", agent="Research", task="a", status=AssignmentStatus.DONE),
            TaskAssignment(id="t2", agent="Coder", task="b", status=AssignmentStatus.DONE, depends_on=["t1"]),
            TaskAssignment(
                id="t3", agent="Reviewer", task="c", status=AssignmentStatus.RUNNING, depends_on=["t2"]
            ),
        ],
    )
    await store.save_plan(task.id, plan.to_context())
    await store.save_context(
        task.id,
        TaskContext(results={"t1": "r", "t2": "bad code"}, coder_result="bad code").model_dump(),
    )

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

    def retry_msg() -> Message:
        return Message(
            from_agent=REVIEWER,
            to_agent=PLANNER,
            content="审查发现问题，请修改：缺少异常处理",
            message_type=MessageType.RESPONSE,
            task_id=task.id,
            metadata={"needs_retry": True, "assignment_id": "t3"},
        ).with_trace()

    await bus.publish(retry_msg())
    await asyncio.sleep(0.2)

    ctx = TaskContext.model_validate((await store.get(task.id)).context or {})
    assert ctx.loops["t2"].iteration == 1
    assert ctx.loops["t2"].status == "running"

    await bus.publish(retry_msg())
    await asyncio.sleep(0.2)

    final = await store.get(task.id)
    ctx = TaskContext.model_validate(final.context or {})
    assert final.status == TaskStatus.WAITING_APPROVAL
    assert ctx.loops["t2"].status == "failed"
    assert ctx.approval_assignment_id == "t3"
    assert "Loop exceeded" in ctx.approval_message

    await planner.stop()
    await bus.disconnect()
    await store.disconnect()
    await registry.disconnect()


@pytest.mark.asyncio
async def test_planner_ignores_stale_assignment_attempt(isolated_paths, patch_settings):
    from backend.agents.planner import PlannerAgent
    from backend.constants import CODER, PLANNER
    from backend.core.llm import LLMClient
    from backend.core.message_bus import InMemoryMessageBus
    from backend.core.registry import AgentRegistry
    from backend.core.services import AgentServices
    from backend.core.shared_memory import InMemorySharedMemory
    from backend.core.task_store import TaskStore
    from backend.models.message import Message, MessageType
    from backend.models.task import TaskStatus
    from backend.tools.registry import ToolRegistry

    patch_settings(enabled_agents="planner,research,coder,reviewer")

    registry = AgentRegistry(isolated_paths["registry"])
    await registry.connect()
    store = TaskStore(isolated_paths["tasks"])
    await store.connect()
    task = await store.create("stale attempt", status=TaskStatus.RUNNING)

    plan = TaskPlan(
        summary="pipe",
        assignments=[
            TaskAssignment(
                id="t1",
                agent=CODER,
                task="code",
                status=AssignmentStatus.RUNNING,
                attempt=2,
            ),
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

    stale = Message(
        from_agent=CODER,
        to_agent=PLANNER,
        content="old result",
        message_type=MessageType.RESPONSE,
        task_id=task.id,
        metadata={"assignment_id": "t1", "attempt": 1},
    ).with_trace()
    await bus.publish(stale)
    await asyncio.sleep(0.15)

    current = TaskContext.plan_from_record((await store.get(task.id)).plan)
    assignment = current.find_assignment(assignment_id="t1")
    assert assignment.status == AssignmentStatus.RUNNING
    assert assignment.attempt == 2
    assert (await store.get(task.id)).result is None

    fresh = Message(
        from_agent=CODER,
        to_agent=PLANNER,
        content="new result",
        message_type=MessageType.RESPONSE,
        task_id=task.id,
        metadata={"assignment_id": "t1", "attempt": 2},
    ).with_trace()
    await bus.publish(fresh)
    await asyncio.sleep(0.15)

    final = await store.get(task.id)
    current = TaskContext.plan_from_record(final.plan)
    assert current.find_assignment(assignment_id="t1").status == AssignmentStatus.DONE
    assert final.status == TaskStatus.COMPLETED

    await planner.stop()
    await bus.disconnect()
    await store.disconnect()
    await registry.disconnect()
