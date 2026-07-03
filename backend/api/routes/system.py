"""Tools, memory, traces, plan, WebSocket."""

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect

from backend.api.deps import clamp_limit, require_role
from backend.api.schemas import MemoryQueryRequest
from backend.auth import get_auth_context, verify_ws_api_key
from backend.core.tenant_access import filter_messages_for_tenant, require_task_for_tenant
from backend.models.auth import AuthContext, Role
from backend.core.runtime import list_runtimes
from backend.platform import platform

router = APIRouter(tags=["system"])


@router.get("/workspace/validate")
async def validate_workspace(
    path: str = "",
    _: AuthContext = Depends(require_role(Role.VIEWER)),
):
    from backend.core.project_workspace import allowed_workspace_roots, check_workspace_path

    roots = [str(p) for p in allowed_workspace_roots()]
    result = check_workspace_path(path)
    return {
        "valid": result.valid,
        "detail": result.detail,
        "path": result.path,
        "will_create": result.will_create,
        "allowed_roots": roots,
    }


@router.get("/runtimes", dependencies=[Depends(get_auth_context)])
async def get_runtimes():
    return {"runtimes": list_runtimes()}


@router.get("/tools", dependencies=[Depends(get_auth_context)])
async def list_tools():
    return {"tools": platform.tools.list_tools()}


@router.get("/plugins/validate", dependencies=[Depends(get_auth_context)])
async def validate_plugins():
    from backend.plugins.validate import validate_manifest

    return validate_manifest()


@router.post("/memory/query")
async def query_memory(
    req: MemoryQueryRequest,
    auth: AuthContext = Depends(require_role(Role.VIEWER)),
):
    if not platform.shared_memory:
        return {"entries": []}
    if req.task_id:
        task = await require_task_for_tenant(platform.task_store, req.task_id, auth.tenant_id)
        if not task:
            raise HTTPException(status_code=404, detail=f"Task '{req.task_id}' not found")
    entries = await platform.shared_memory.query(
        req.query,
        limit=req.limit,
        task_id=req.task_id,
        tenant_id=auth.tenant_id,
    )
    return {"entries": [e.model_dump() for e in entries]}


@router.get("/traces/{trace_id}")
async def get_trace(
    trace_id: str,
    auth: AuthContext = Depends(require_role(Role.VIEWER)),
):
    messages = await platform.task_store.find_by_trace(trace_id, tenant_id=auth.tenant_id)
    if not messages:
        in_memory = await filter_messages_for_tenant(
            platform.task_store,
            [m for m in platform.message_log if m.trace_id == trace_id],
            auth.tenant_id,
        )
        messages = in_memory
    if not messages:
        raise HTTPException(status_code=404, detail=f"Trace '{trace_id}' not found")
    return {"trace_id": trace_id, "messages": [m.model_dump() for m in messages]}


@router.get("/plan", dependencies=[Depends(get_auth_context)])
async def get_current_plan(
    task_id: str = "",
    auth: AuthContext = Depends(require_role(Role.VIEWER)),
):
    if task_id:
        task = await platform.task_store.get(task_id, tenant_id=auth.tenant_id)
        return {"task_id": task_id, "plan": task.plan if task else None}

    for task in await platform.task_store.list_tasks(limit=20, tenant_id=auth.tenant_id):
        if task.plan:
            return {"task_id": task.id, "plan": task.plan}
    return {"plan": None}


@router.websocket("/ws/messages")
async def websocket_messages(websocket: WebSocket):
    auth = await verify_ws_api_key(websocket)
    if not auth:
        await websocket.close(code=4401)
        return
    await websocket.accept()

    async def on_message(message):
        visible = await filter_messages_for_tenant(
            platform.task_store,
            [message],
            auth.tenant_id,
        )
        if visible:
            await websocket.send_json(message.model_dump(mode="json"))

    platform.add_message_listener(on_message)

    try:
        recent = await filter_messages_for_tenant(
            platform.task_store,
            platform.message_log[-20:],
            auth.tenant_id,
        )
        for msg in recent:
            await websocket.send_json(msg.model_dump(mode="json"))

        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        platform.remove_message_listener(on_message)
