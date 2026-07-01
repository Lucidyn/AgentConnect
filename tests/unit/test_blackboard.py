"""Unit tests for blackboard collaboration helpers."""

from __future__ import annotations

from backend.core.blackboard import format_blackboard, post_entry, record_negotiation
from backend.core.plan_dispatch import build_assignment_task
from backend.core.plan_orchestrator import _extract_questions
from backend.models.plan import TaskAssignment, TaskPlan
from backend.models.task_context import TaskContext, WorkspaceState


def test_post_entry_and_format_blackboard():
    ctx = TaskContext(collaboration_mode="blackboard", negotiation=True)
    post_entry(ctx, author="Research", content="发现三篇论文", entry_type="fact")
    post_entry(ctx, author="Writer", content="目标读者是谁？", entry_type="question")
    text = format_blackboard(ctx.workspace)
    assert "协作黑板" in text
    assert "Research" in text
    assert "目标读者" in text


def test_build_assignment_task_includes_blackboard():
    plan = TaskPlan(
        summary="s",
        assignments=[
            TaskAssignment(id="t1", agent="Research", task="调研", depends_on=[]),
            TaskAssignment(id="t2", agent="Writer", task="写作", depends_on=["t1"]),
        ],
    )
    ctx = TaskContext(
        collaboration_mode="blackboard",
        negotiation=True,
        results={"t1": "调研结果"},
    )
    ctx.workspace.open_questions.append("需要英文还是中文？")
    post_entry(ctx, author="Research", content="调研结果摘要", entry_type="fact")
    task_text = build_assignment_task(plan.assignments[1], plan, ctx)
    assert "协作黑板" in task_text
    assert "协商" in task_text
    assert "调研结果" in task_text


def test_extract_questions_from_agent_output():
    content = "结论如下。\n目标语言是英文吗？\n问题：是否需要保留术语？"
    questions = _extract_questions(content)
    assert len(questions) >= 2


def test_record_negotiation():
    ctx = TaskContext()
    record_negotiation(ctx, "Research 答复：使用中文")
    assert ctx.workspace.negotiation_log
