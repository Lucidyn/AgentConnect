"""Plan template and custom DAG validation routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from backend.api.deps import require_role
from backend.api.schemas import ImportTemplateRequest, SaveTemplateRequest, ValidatePlanRequest
from backend.core.plan_templates import get_template, list_templates, plan_from_custom
from backend.core.saved_templates import delete_saved, get_saved, list_saved, save_template
from backend.models.auth import AuthContext, Role

router = APIRouter(prefix="/templates", tags=["templates"])


@router.get("")
async def list_plan_templates(auth: AuthContext = Depends(require_role(Role.VIEWER))):
    builtin = list_templates()
    saved = list_saved(tenant_id=auth.tenant_id)
    return {"templates": builtin + saved}


@router.get("/marketplace")
async def list_marketplace_templates(_: AuthContext = Depends(require_role(Role.VIEWER))):
    from backend.core.template_marketplace import list_marketplace

    return {"templates": list_marketplace()}


@router.post("/marketplace/{template_id}/fork")
async def fork_marketplace_template(
    template_id: str,
    auth: AuthContext = Depends(require_role(Role.OPERATOR)),
):
    from backend.core.template_marketplace import fork_marketplace_template

    payload = fork_marketplace_template(template_id, auth.tenant_id)
    if not payload:
        raise HTTPException(status_code=404, detail=f"Marketplace template '{template_id}' not found")
    return {"template": payload}


@router.get("/saved/{template_id}/export")
async def export_saved_template(
    template_id: str,
    auth: AuthContext = Depends(require_role(Role.VIEWER)),
):
    from backend.core.template_marketplace import export_saved_template

    payload = export_saved_template(template_id, auth.tenant_id)
    if not payload:
        raise HTTPException(status_code=404, detail=f"Saved template '{template_id}' not found")
    return payload


@router.post("/import")
async def import_template(
    req: ImportTemplateRequest,
    auth: AuthContext = Depends(require_role(Role.OPERATOR)),
):
    from backend.core.template_marketplace import import_template_payload

    payload = import_template_payload(req.template, auth.tenant_id)
    return {"template": payload}


@router.get("/eval/run")
async def run_template_evals(_: AuthContext = Depends(require_role(Role.VIEWER))):
    from backend.core.eval_harness import run_all_evals

    return run_all_evals()


@router.get("/saved")
async def list_saved_templates(auth: AuthContext = Depends(require_role(Role.VIEWER))):
    return {"templates": list_saved(tenant_id=auth.tenant_id)}


@router.post("/saved")
async def create_saved_template(
    req: SaveTemplateRequest,
    auth: AuthContext = Depends(require_role(Role.OPERATOR)),
):
    try:
        plan_from_custom(req.custom_plan, "示例任务")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    payload = save_template(
        name=req.name,
        description=req.description,
        plan=req.custom_plan,
        tenant_id=auth.tenant_id,
    )
    return {"template": payload}


@router.delete("/saved/{template_id}")
async def remove_saved_template(
    template_id: str,
    auth: AuthContext = Depends(require_role(Role.OPERATOR)),
):
    if not delete_saved(template_id, tenant_id=auth.tenant_id):
        raise HTTPException(status_code=404, detail=f"Saved template '{template_id}' not found")
    return {"deleted": template_id}


@router.get("/{template_id}")
async def get_plan_template(
    template_id: str,
    auth: AuthContext = Depends(require_role(Role.VIEWER)),
):
    template = get_template(template_id)
    if template:
        return {"template": template.model_dump()}
    saved = get_saved(template_id, tenant_id=auth.tenant_id)
    if not saved:
        raise HTTPException(status_code=404, detail=f"Template '{template_id}' not found")
    return {"template": saved}


@router.post("/validate")
async def validate_custom_plan(
    req: ValidatePlanRequest,
    _: AuthContext = Depends(require_role(Role.VIEWER)),
):
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
async def preview_custom_plan(
    req: ValidatePlanRequest,
    _: AuthContext = Depends(require_role(Role.VIEWER)),
):
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
