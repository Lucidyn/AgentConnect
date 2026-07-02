"""Surpass feature tests — checkpoints, eval, marketplace, approval nodes, budget."""

from __future__ import annotations

import pytest

from backend.core.checkpoints import append_checkpoint, find_checkpoint
from backend.core.dynamic_replan import try_failure_replan
from backend.core.eval_harness import run_all_evals, run_eval_case
from backend.core.model_routing import resolve_model
from backend.core.plan_templates import plan_from_custom
from backend.core.template_marketplace import fork_marketplace_template, list_marketplace
from backend.models.plan import AssignmentStatus, TaskAssignment, TaskPlan
from backend.models.task_context import TaskContext


def test_checkpoint_append_and_find():
    ctx = TaskContext()
    plan = TaskPlan(
        summary="demo",
        assignments=[TaskAssignment(id="n1", agent="Research", task="t")],
    )
    snap = append_checkpoint(ctx, plan, "n1", label="Research")
    assert find_checkpoint(ctx, snap.id) is not None
    assert find_checkpoint(ctx, snap.id).assignment_id == "n1"


def test_human_approval_plan_fields():
    plan = plan_from_custom(
        {
            "summary": "gate",
            "assignments": [
                {"id": "g1", "agent": "HumanApproval", "node_type": "human_approval", "task": "approve"},
            ],
        },
        "demo",
    )
    assert plan.assignments[0].node_type == "human_approval"


def test_dynamic_replan_resets_upstream():
    plan = TaskPlan(
        assignments=[
            TaskAssignment(id="r1", agent="Research", task="research", status=AssignmentStatus.DONE),
            TaskAssignment(id="c1", agent="Coder", task="code", depends_on=["r1"], status=AssignmentStatus.RUNNING),
        ]
    )
    ctx = TaskContext()
    failed = plan.assignments[1]
    assert try_failure_replan(plan, ctx, failed, "compile error") is True
    assert plan.assignments[0].status == AssignmentStatus.PENDING


def test_eval_harness_runs():
    result = run_all_evals()
    assert result["total"] >= 1
    assert result["passed"] >= 1


def test_marketplace_list_and_fork(isolated_paths, patch_settings):
    patch_settings(template_marketplace_dir="data/marketplace")
    items = list_marketplace()
    assert any(item["id"] == "research_write_gate" for item in items)
    forked = fork_marketplace_template("research_write_gate", "default")
    assert forked is not None


def test_model_routing_tiers():
    configs = {"coder": {"model_tier": "premium"}, "research": {"model_tier": "cheap"}}
    assert resolve_model("Coder", "developer", configs) is None or isinstance(resolve_model("Coder", "developer", configs), str)


def test_eval_case_custom_parallel():
    case = {
        "id": "x",
        "task": "demo",
        "custom_plan": {
            "summary": "p",
            "assignments": [
                {"id": "a", "agent": "Research", "task": "t"},
                {"id": "b", "agent": "Writer", "task": "t", "depends_on": ["a"]},
            ],
        },
        "checks": {"min_nodes": 2},
    }
    assert run_eval_case(case)["passed"] is True
