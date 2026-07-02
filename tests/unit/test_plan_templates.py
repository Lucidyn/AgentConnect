"""Unit tests for plan templates and custom DAG plans."""

from __future__ import annotations

import pytest

from backend.core.plan_templates import get_template, list_templates, plan_from_custom
from backend.models.plan import TaskPlan


def test_list_templates_includes_research_write_translate():
    templates = list_templates()
    ids = {item["id"] for item in templates}
    assert "research_write_translate" in ids
    assert "hybrid_report" in ids


def test_template_to_plan_replaces_task_placeholder():
    template = get_template("research_write_translate")
    assert template is not None
    plan = template.to_plan("写一篇 AI 科普", registry=None)
    assert isinstance(plan, TaskPlan)
    assert len(plan.assignments) == 4
    assert plan.assignments[0].agent == "Research"
    assert plan.assignments[2].agent == "Translator"
    assert "AI 科普" in plan.assignments[1].task


def test_hybrid_report_pipeline_order():
    template = get_template("hybrid_report")
    assert template is not None
    plan = template.to_plan("行业分析报告", registry=None)
    agents = [item.agent for item in plan.assignments]
    assert agents == ["Research", "Analyst", "Writer", "Reviewer"]
    assert plan.assignments[2].depends_on == ["t2"]


def test_custom_plan_validation_rejects_cycle():
    custom = {
        "summary": "bad",
        "assignments": [
            {"id": "a", "agent": "Writer", "task": "x", "depends_on": ["b"]},
            {"id": "b", "agent": "Research", "task": "y", "depends_on": ["a"]},
        ],
    }
    with pytest.raises(ValueError, match="cycle"):
        plan_from_custom(custom, "demo", registry=None)


def test_custom_plan_accepts_valid_dag():
    custom = {
        "summary": "自定义：{task}",
        "steps": ["写", "审"],
        "assignments": [
            {"id": "t1", "agent": "Writer", "task": "写：{task}", "depends_on": []},
            {"id": "t2", "agent": "Reviewer", "task": "审：{task}", "depends_on": ["t1"]},
        ],
    }
    plan = plan_from_custom(custom, "测试任务", registry=None)
    assert plan.summary == "自定义：测试任务"
    assert len(plan.assignments) == 2
