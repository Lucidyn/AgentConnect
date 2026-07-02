"""Golden-task eval harness for template/regression checks."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from backend.core.plan_templates import plan_from_custom
from backend.core.plan_validate import validate_assignments


def _eval_file() -> Path:
    return Path(__file__).resolve().parents[2] / "tests" / "evals" / "golden_tasks.yaml"


def load_eval_cases() -> list[dict[str, Any]]:
    path = _eval_file()
    if not path.exists():
        return []
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return list(data.get("cases") or [])


def run_eval_case(case: dict[str, Any]) -> dict[str, Any]:
    case_id = case.get("id", "unknown")
    task = case.get("task", "demo")
    checks = case.get("checks") or {}
    errors: list[str] = []

    custom_plan = case.get("custom_plan")
    template_id = case.get("template_id")
    if custom_plan:
        try:
            plan = plan_from_custom(custom_plan, task)
        except ValueError as exc:
            errors.append(str(exc))
            plan = None
    elif template_id:
        from backend.core.plan_templates import get_template

        template = get_template(template_id)
        if not template:
            errors.append(f"Template '{template_id}' not found")
            plan = None
        else:
            plan = template.to_plan(task)
    else:
        errors.append("case needs custom_plan or template_id")
        plan = None

    if plan:
        validation = validate_assignments(plan.assignments)
        if validation:
            errors.extend(validation)
        agents = [item.agent for item in plan.assignments]
        expect_agents = checks.get("agents") or []
        for agent in expect_agents:
            if agent not in agents:
                errors.append(f"missing agent: {agent}")
        min_nodes = int(checks.get("min_nodes") or 0)
        if min_nodes and len(plan.assignments) < min_nodes:
            errors.append(f"expected >= {min_nodes} nodes, got {len(plan.assignments)}")
        expect_summary = checks.get("summary_contains")
        if expect_summary and expect_summary not in plan.summary:
            errors.append(f"summary missing '{expect_summary}'")

    return {
        "id": case_id,
        "passed": not errors,
        "errors": errors,
    }


def run_all_evals() -> dict[str, Any]:
    cases = load_eval_cases()
    results = [run_eval_case(case) for case in cases]
    passed = sum(1 for item in results if item["passed"])
    return {
        "total": len(results),
        "passed": passed,
        "failed": len(results) - passed,
        "results": results,
    }
