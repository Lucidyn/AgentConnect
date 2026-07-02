"""Message bus and dead-letter routes."""

from fastapi import APIRouter, Depends, HTTPException

from backend.api.deps import clamp_limit, require_role
from backend.core.tenant_access import filter_messages_for_tenant, message_task_id, task_belongs_to_tenant
from backend.models.auth import AuthContext, Role
from backend.platform import platform

router = APIRouter(prefix="/messages", tags=["messages"])


@router.get("")
async def get_messages(
    auth: AuthContext = Depends(require_role(Role.VIEWER)),
    limit: int = Depends(clamp_limit),
):
    messages = await filter_messages_for_tenant(
        platform.task_store,
        platform.message_log[-limit * 3 :],
        auth.tenant_id,
    )
    messages = messages[-limit:]
    return {"messages": [m.model_dump() for m in messages], "total": len(messages)}


@router.get("/dead-letter")
async def list_dead_letters(
    auth: AuthContext = Depends(require_role(Role.ADMIN)),
    limit: int = Depends(clamp_limit),
):
    messages = await platform.message_outbox.list_failed(limit=limit * 3)
    messages = await filter_messages_for_tenant(platform.task_store, messages, auth.tenant_id)
    messages = messages[:limit]
    return {"messages": [m.model_dump() for m in messages], "total": len(messages)}


@router.post("/dead-letter/{message_id}/retry")
async def retry_dead_letter(
    message_id: str,
    auth: AuthContext = Depends(require_role(Role.ADMIN)),
):
    failed = await platform.message_outbox.list_failed(limit=500)
    target = next((m for m in failed if m.id == message_id), None)
    if not target:
        raise HTTPException(
            status_code=404,
            detail=f"Message '{message_id}' not found or not retryable",
        )
    task_id = message_task_id(target)
    if not await task_belongs_to_tenant(platform.task_store, task_id, auth.tenant_id):
        raise HTTPException(status_code=404, detail=f"Message '{message_id}' not found")
    ok = await platform.retry_dead_letter(message_id)
    if not ok:
        raise HTTPException(
            status_code=404,
            detail=f"Message '{message_id}' not found or not retryable",
        )
    return {"message_id": message_id, "status": "requeued"}


@router.delete("/dead-letter")
async def purge_dead_letters(auth: AuthContext = Depends(require_role(Role.ADMIN))):
    failed = await platform.message_outbox.list_failed(limit=1000)
    tenant_failed = await filter_messages_for_tenant(platform.task_store, failed, auth.tenant_id)
    removed = 0
    for message in tenant_failed:
        if await platform.message_outbox.delete_failed(message.id):
            removed += 1
    return {"removed": removed, "status": "purged"}
