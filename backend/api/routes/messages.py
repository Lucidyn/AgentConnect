"""Message bus and dead-letter routes."""

from fastapi import APIRouter, Depends

from backend.auth import verify_api_key
from backend.platform import platform

router = APIRouter(prefix="/messages", tags=["messages"])


@router.get("")
async def get_messages(limit: int = 50):
    messages = platform.message_log[-limit:]
    return {"messages": [m.model_dump() for m in messages], "total": len(messages)}


@router.get("/dead-letter")
async def list_dead_letters(limit: int = 50):
    messages = await platform.message_outbox.list_failed(limit=limit)
    return {"messages": [m.model_dump() for m in messages], "total": len(messages)}


@router.post("/dead-letter/{message_id}/retry", dependencies=[Depends(verify_api_key)])
async def retry_dead_letter(message_id: str):
    ok = await platform.retry_dead_letter(message_id)
    if not ok:
        return {"error": f"Message '{message_id}' not found or not retryable"}
    return {"message_id": message_id, "status": "requeued"}


@router.delete("/dead-letter", dependencies=[Depends(verify_api_key)])
async def purge_dead_letters():
    removed = await platform.purge_dead_letters()
    return {"removed": removed, "status": "purged"}
