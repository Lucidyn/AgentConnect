"""Integration tests for planner retry, loop limits, and stale attempts."""

import asyncio

import pytest

from backend.constants import CODER, PLANNER, REVIEWER
from backend.core.plan_validate import validate_assignments
from backend.models.message import Message, MessageIntent, MessageType
from backend.models.plan import AssignmentStatus, TaskAssignment, TaskPlan
from backend.models.task import TaskStatus
from backend.models.task_context import TaskContext


@pytest.mark.asyncio
async def test_parse_plan_rejects_invalid_llm_plan(planner_stack):
    invalid = (
        '{"summary":"bad","assignments":['
        '{"id":"t1","agent":"Coder","task":"x","depends_on":["t2"]},'
        '{"id":"t2","agent":"Research","task":"y","depends_on":["t1"]}'
        "]}"
    )
    plan = planner_stack.planner._parse_plan(
        invalid, "test task", planner_stack.planner._fallback_plan("test task")
    )
    assert validate_assignments(plan.assignments) == []


@pytest.mark.asyncio
async def test_reviewer_retry_goes_through_planner(planner_stack):
    store = planner_stack.store
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

    retry_msg = Message(
        from_agent=REVIEWER,
        to_agent=PLANNER,
        content="审查发现问题，请修改：缺少异常处理",
        message_type=MessageType.RESPONSE,
        task_id=task.id,
        metadata={
            "intent": MessageIntent.RETRY_REQUEST.value,
            "needs_retry": True,
            "assignment_id": "t3",
        },
    ).with_trace()

    await planner_stack.bus.publish(retry_msg)
    await asyncio.sleep(0.2)

    reloaded = TaskPlan.from_record((await store.get(task.id)).plan)
    coder = reloaded.find_assignment(assignment_id="t2")
    assert coder.status == AssignmentStatus.RUNNING
    reviewer = reloaded.find_assignment(assignment_id="t3")
    assert reviewer.status == AssignmentStatus.PENDING

    saved_ctx = TaskContext.model_validate((await store.get(task.id)).context or {})
    assert "缺少异常处理" in saved_ctx.retry_feedback


@pytest.mark.asyncio
async def test_reviewer_loop_enters_approval_after_max_iterations(
    isolated_paths, patch_settings, planner_stack_factory
):
    stack = await planner_stack_factory(loop_max_iterations=1)
    store = stack.store
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

    def retry_msg() -> Message:
        return Message(
            from_agent=REVIEWER,
            to_agent=PLANNER,
            content="审查发现问题，请修改：缺少异常处理",
            message_type=MessageType.RESPONSE,
            task_id=task.id,
            metadata={
                "intent": MessageIntent.RETRY_REQUEST.value,
                "needs_retry": True,
                "assignment_id": "t3",
            },
        ).with_trace()

    await stack.bus.publish(retry_msg())
    await asyncio.sleep(0.2)

    ctx = TaskContext.model_validate((await store.get(task.id)).context or {})
    assert ctx.loops["t2"].iteration == 1
    assert ctx.loops["t2"].status == "running"

    await stack.bus.publish(retry_msg())
    await asyncio.sleep(0.2)

    final = await store.get(task.id)
    ctx = TaskContext.model_validate(final.context or {})
    assert final.status == TaskStatus.WAITING_APPROVAL
    assert ctx.loops["t2"].status == "failed"
    assert ctx.approval_assignment_id == "t3"
    assert "Loop exceeded" in ctx.approval_message


@pytest.mark.asyncio
async def test_planner_ignores_stale_assignment_attempt(planner_stack):
    store = planner_stack.store
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

    stale = Message(
        from_agent=CODER,
        to_agent=PLANNER,
        content="old result",
        message_type=MessageType.RESPONSE,
        task_id=task.id,
        metadata={"assignment_id": "t1", "attempt": 1},
    ).with_trace()
    await planner_stack.bus.publish(stale)
    await asyncio.sleep(0.15)

    current = TaskPlan.from_record((await store.get(task.id)).plan)
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
    await planner_stack.bus.publish(fresh)
    await asyncio.sleep(0.15)

    final = await store.get(task.id)
    current = TaskPlan.from_record(final.plan)
    assert current.find_assignment(assignment_id="t1").status == AssignmentStatus.DONE
    assert final.status == TaskStatus.COMPLETED
