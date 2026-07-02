"""Load and instantiate user-defined plan templates."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

from backend.config import settings
from backend.core.plan_validate import validate_assignments
from backend.core.registry import AgentRegistry
from backend.models.plan import TaskAssignment, TaskPlan

logger = logging.getLogger(__name__)

_DEFAULT_TEMPLATE_PATH = Path(__file__).resolve().parents[2] / "plugins" / "plan_templates.yaml"


class PlanTemplate(BaseModel):
    id: str
    name: str = ""
    description: str = ""
    collaboration_mode: str = "planner"
    negotiation: bool = False
    summary: str = ""
    steps: list[str] = Field(default_factory=list)
    assignments: list[dict[str, Any]] = Field(default_factory=list)

    def to_plan(self, task: str, registry: AgentRegistry | None = None) -> TaskPlan:
        assignments: list[TaskAssignment] = []
        for item in self.assignments:
            agent_name = item.get("agent", "")
            if registry and not registry.get(agent_name):
                discovered = registry.best_for_task(item.get("task", task))
                if discovered:
                    agent_name = discovered.name
            assignments.append(
                TaskAssignment(
                    id=item["id"],
                    agent=agent_name,
                    task=item.get("task", task).format(task=task),
                    depends_on=item.get("depends_on", []),
                    reason=item.get("reason", ""),
                    node_type=item.get("node_type", "agent"),
                    requires_approval=bool(item.get("requires_approval", False)),
                )
            )
        return TaskPlan(
            summary=self.summary.format(task=task),
            steps=list(self.steps),
            assignments=assignments,
        )


def _template_path() -> Path:
    custom = getattr(settings, "plan_templates_path", "") or ""
    if custom:
        path = Path(custom)
        if path.exists():
            return path
    return _DEFAULT_TEMPLATE_PATH


def load_templates() -> dict[str, PlanTemplate]:
    path = _template_path()
    if not path.exists():
        logger.warning("Plan templates file not found: %s", path)
        return {}
    with path.open(encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    templates: dict[str, PlanTemplate] = {}
    for item in data.get("templates", []):
        try:
            template = PlanTemplate.model_validate(item)
            templates[template.id] = template
        except Exception as exc:
            logger.warning("Invalid plan template entry: %s", exc)
    return templates


def get_template(template_id: str) -> PlanTemplate | None:
    template = load_templates().get(template_id)
    if template:
        return template
    from backend.core.saved_templates import get_saved

    saved = get_saved(template_id)
    if not saved:
        return None
    plan = saved.get("plan") or {}
    return PlanTemplate(
        id=saved.get("id", template_id),
        name=saved.get("name", template_id),
        description=saved.get("description", ""),
        collaboration_mode="planner",
        negotiation=False,
        summary=plan.get("summary", ""),
        steps=plan.get("steps", []),
        assignments=plan.get("assignments", []),
    )


def list_templates() -> list[dict[str, Any]]:
    return [
        {
            "id": template.id,
            "name": template.name,
            "description": template.description,
            "collaboration_mode": template.collaboration_mode,
            "negotiation": template.negotiation,
            "assignment_count": len(template.assignments),
            "agents": [item.get("agent") for item in template.assignments],
        }
        for template in load_templates().values()
    ]


def plan_from_custom(custom: dict[str, Any], task: str, registry: AgentRegistry | None = None) -> TaskPlan:
    """Build TaskPlan from user/visual editor JSON."""
    assignments: list[TaskAssignment] = []
    for item in custom.get("assignments", []):
        agent_name = item.get("agent", "")
        if registry and agent_name and not registry.get(agent_name):
            discovered = registry.best_for_task(item.get("task", task))
            if discovered:
                agent_name = discovered.name
        task_text = item.get("task", task)
        if "{task}" in task_text:
            task_text = task_text.format(task=task)
        assignments.append(
            TaskAssignment(
                id=item["id"],
                agent=agent_name,
                task=task_text,
                depends_on=item.get("depends_on", []),
                reason=item.get("reason", ""),
                node_type=item.get("node_type", "agent"),
                requires_approval=bool(item.get("requires_approval", False)),
            )
        )
    summary = custom.get("summary", f"自定义计划：{task}")
    if "{task}" in summary:
        summary = summary.format(task=task)
    plan = TaskPlan(
        summary=summary,
        steps=custom.get("steps", []),
        assignments=assignments,
    )
    errors = validate_assignments(plan.assignments)
    if errors:
        raise ValueError("; ".join(errors))
    return plan
