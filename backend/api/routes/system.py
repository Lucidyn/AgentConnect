"""Tools, memory, traces, plan, WebSocket."""

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect

from backend.api.schemas import MemoryQueryRequest
from backend.auth import verify_api_key, verify_ws_api_key
from backend.core.runtime import list_runtimes
from backend.platform import platform

router = APIRouter(tags=["system"])


@router.get("/runtimes")
async def get_runtimes():
    return {"runtimes": list_runtimes()}


@router.get("/tools")
async def list_tools():
    return {"tools": platform.tools.list_tools()}


@router.post("/memory/query", dependencies=[Depends(verify_api_key)])
async def query_memory(req: MemoryQueryRequest):
    if not platform.shared_memory:
        return {"entries": []}
    entries = await platform.shared_memory.query(
        req.query, limit=req.limit, task_id=req.task_id
    )
    return {"entries": [e.model_dump() for e in entries]}


@router.get("/traces/{trace_id}", dependencies=[Depends(verify_api_key)])
async def get_trace(trace_id: str):
    messages = await platform.task_store.find_by_trace(trace_id)
    if not messages:
        messages = [m for m in platform.message_log if m.trace_id == trace_id]
    return {"trace_id": trace_id, "messages": [m.model_dump() for m in messages]}


@router.get("/plan", dependencies=[Depends(verify_api_key)])
async def get_current_plan(task_id: str = ""):
    if task_id:
        task = await platform.task_store.get(task_id)
        return {"task_id": task_id, "plan": task.plan if task else None}

    for task in await platform.task_store.list_tasks(limit=20):
        if task.plan:
            return {"task_id": task.id, "plan": task.plan}
    return {"plan": None}


@router.websocket("/ws/messages")
async def websocket_messages(websocket: WebSocket):
    if not await verify_ws_api_key(websocket):
        await websocket.close(code=4401)
        return
    await websocket.accept()

    async def on_message(message):
        await websocket.send_json(message.model_dump(mode="json"))

    platform.add_message_listener(on_message)

    try:
        for msg in platform.message_log[-20:]:
            await websocket.send_json(msg.model_dump(mode="json"))

        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        platform.remove_message_listener(on_message)
