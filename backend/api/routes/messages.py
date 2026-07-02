"""Message bus and dead-letter routes."""

from fastapi import APIRouter, Depends, HTTPException

from backend.api.deps import clamp_limit
from backend.auth import get_auth_context
from backend.platform import platform

router = APIRouter(
    prefix="/messages",
    tags=["messages"],
    dependencies=[Depends(get_auth_context)],
)


@router.get("")
async def get_messages(limit: int = Depends(clamp_limit)):
    messages = platform.message_log[-limit:]
    return {"messages": [m.model_dump() for m in messages], "total": len(messages)}


@router.get("/dead-letter")
async def list_dead_letters(limit: int = Depends(clamp_limit)):
    messages = await platform.message_outbox.list_failed(limit=limit)
    return {"messages": [m.model_dump() for m in messages], "total": len(messages)}


@router.post("/dead-letter/{message_id}/retry")
async def retry_dead_letter(message_id: str):
    ok = await platform.retry_dead_letter(message_id)
    if not ok:
        raise HTTPException(
            status_code=404,
            detail=f"Message '{message_id}' not found or not retryable",
        )
    return {"message_id": message_id, "status": "requeued"}


@router.delete("/dead-letter")
async def purge_dead_letters():
    removed = await platform.purge_dead_letters()
    return {"removed": removed, "status": "purged"}
