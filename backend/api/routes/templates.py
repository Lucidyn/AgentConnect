"""Plan template and custom DAG validation routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from backend.api.schemas import ValidatePlanRequest
from backend.auth import verify_api_key
from backend.core.plan_templates import get_template, list_templates, plan_from_custom

router = APIRouter(
    prefix="/templates",
    tags=["templates"],
    dependencies=[Depends(verify_api_key)],
)


@router.get("")
async def list_plan_templates():
    return {"templates": list_templates()}


@router.get("/{template_id}")
async def get_plan_template(template_id: str):
    template = get_template(template_id)
    if not template:
        raise HTTPException(status_code=404, detail=f"Template '{template_id}' not found")
    return {"template": template.model_dump()}


@router.post("/validate")
async def validate_custom_plan(req: ValidatePlanRequest):
    try:
        plan = plan_from_custom(req.custom_plan, req.task or "示例任务")
        return {
            "valid": True,
            "summary": plan.summary,
            "assignment_count": len(plan.assignments),
            "agents": [item.agent for item in plan.assignments],
        }
    except ValueError as exc:
        return {"valid": False, "errors": [str(exc)]}


@router.post("/preview")
async def preview_custom_plan(req: ValidatePlanRequest):
    """Validate and return full assignment list for the DAG editor."""
    try:
        plan = plan_from_custom(req.custom_plan, req.task or "示例任务")
    except ValueError as exc:
        return {"valid": False, "errors": [str(exc)]}
    return {
        "valid": True,
        "plan": {
            "summary": plan.summary,
            "steps": plan.steps,
            "assignments": [item.model_dump() for item in plan.assignments],
        },
    }
