"""Tenant and API key administration."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from backend.api.deps import require_role
from backend.api.schemas import CreateApiKeyRequest, CreateTenantRequest, TenantBudgetRequest
from backend.models.auth import DEFAULT_TENANT_ID, AuthContext, Role
from backend.platform import platform

router = APIRouter(prefix="/admin", tags=["admin"])


def _can_manage_tenant(auth: AuthContext, tenant_id: str) -> bool:
    if auth.tenant_id == tenant_id:
        return True
    return auth.tenant_id == DEFAULT_TENANT_ID and auth.role == Role.ADMIN


@router.post("/tenants")
async def create_tenant(
    req: CreateTenantRequest,
    auth: AuthContext = Depends(require_role(Role.ADMIN)),
):
    if not platform.tenant_store:
        raise HTTPException(status_code=503, detail="Tenant store unavailable")
    existing = await platform.tenant_store.get_tenant(req.tenant_id)
    if existing:
        raise HTTPException(status_code=409, detail=f"Tenant '{req.tenant_id}' already exists")
    tenant = await platform.tenant_store.create_tenant(req.tenant_id, req.name)
    return {"tenant": tenant}


@router.get("/tenants/{tenant_id}/keys")
async def list_tenant_keys(
    tenant_id: str,
    auth: AuthContext = Depends(require_role(Role.ADMIN)),
):
    if not _can_manage_tenant(auth, tenant_id):
        raise HTTPException(status_code=403, detail="Cannot list keys for another tenant")
    if not platform.tenant_store:
        raise HTTPException(status_code=503, detail="Tenant store unavailable")
    keys = await platform.tenant_store.list_api_keys(tenant_id)
    return {"tenant_id": tenant_id, "keys": keys}


@router.post("/tenants/{tenant_id}/keys")
async def create_tenant_key(
    tenant_id: str,
    req: CreateApiKeyRequest,
    auth: AuthContext = Depends(require_role(Role.ADMIN)),
):
    if not _can_manage_tenant(auth, tenant_id):
        raise HTTPException(status_code=403, detail="Cannot create keys for another tenant")
    if not platform.tenant_store:
        raise HTTPException(status_code=503, detail="Tenant store unavailable")
    try:
        raw, meta = await platform.tenant_store.create_api_key(
            tenant_id,
            name=req.name,
            role=Role(req.role),
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"key": raw, "meta": meta}


@router.delete("/tenants/{tenant_id}/keys/{key_id}")
async def revoke_tenant_key(
    tenant_id: str,
    key_id: str,
    auth: AuthContext = Depends(require_role(Role.ADMIN)),
):
    if not _can_manage_tenant(auth, tenant_id):
        raise HTTPException(status_code=403, detail="Cannot revoke keys for another tenant")
    if not platform.tenant_store:
        raise HTTPException(status_code=503, detail="Tenant store unavailable")
    if not await platform.tenant_store.revoke_api_key(tenant_id, key_id):
        raise HTTPException(status_code=404, detail=f"API key '{key_id}' not found")
    return {"revoked": key_id}


@router.put("/tenants/{tenant_id}/budget")
async def set_tenant_budget(
    tenant_id: str,
    req: TenantBudgetRequest,
    auth: AuthContext = Depends(require_role(Role.ADMIN)),
):
    if not _can_manage_tenant(auth, tenant_id):
        raise HTTPException(status_code=403, detail="Cannot set budget for another tenant")
    if not platform.tenant_store:
        raise HTTPException(status_code=503, detail="Tenant store unavailable")
    if not await platform.tenant_store.set_budget_usd(tenant_id, req.budget_usd):
        raise HTTPException(status_code=404, detail=f"Tenant '{tenant_id}' not found")
    tenant = await platform.tenant_store.get_tenant(tenant_id)
    return {"tenant": tenant}
