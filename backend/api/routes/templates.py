"""Plan template and custom DAG validation routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from backend.api.schemas import SaveTemplateRequest, ValidatePlanRequest
from backend.auth import verify_api_key
from backend.core.plan_templates import get_template, list_templates, plan_from_custom
from backend.core.saved_templates import delete_saved, get_saved, list_saved, save_template

router = APIRouter(
    prefix="/templates",
    tags=["templates"],
    dependencies=[Depends(verify_api_key)],
)


@router.get("")
async def list_plan_templates():
    builtin = list_templates()
    saved = list_saved()
    return {"templates": builtin + saved}


@router.get("/saved")
async def list_saved_templates():
    return {"templates": list_saved()}


@router.post("/saved")
async def create_saved_template(req: SaveTemplateRequest):
    try:
        plan_from_custom(req.custom_plan, "示例任务")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    payload = save_template(
        name=req.name,
        description=req.description,
        plan=req.custom_plan,
    )
    return {"template": payload}


@router.delete("/saved/{template_id}")
async def remove_saved_template(template_id: str):
    if not delete_saved(template_id):
        raise HTTPException(status_code=404, detail=f"Saved template '{template_id}' not found")
    return {"deleted": template_id}


@router.get("/{template_id}")
async def get_plan_template(template_id: str):
    template = get_template(template_id)
    if template:
        return {"template": template.model_dump()}
    saved = get_saved(template_id)
    if not saved:
        raise HTTPException(status_code=404, detail=f"Template '{template_id}' not found")
    return {"template": saved}


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
