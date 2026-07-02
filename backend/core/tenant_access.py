"""Tenant-scoped access helpers for messages, traces, and memory."""

from __future__ import annotations

from backend.models.auth import DEFAULT_TENANT_ID
from backend.models.message import Message
from backend.models.task import TaskRecord


def message_task_id(message: Message) -> str:
    return message.task_id or str(message.metadata.get("task_id", ""))


async def task_belongs_to_tenant(
    task_store,
    task_id: str,
    tenant_id: str,
) -> bool:
    if not task_id:
        return False
    task = await task_store.get(task_id)
    return task is not None and task.tenant_id == tenant_id


async def filter_messages_for_tenant(
    task_store,
    messages: list[Message],
    tenant_id: str,
) -> list[Message]:
    cache: dict[str, bool] = {}
    filtered: list[Message] = []
    for message in messages:
        task_id = message_task_id(message)
        if not task_id:
            continue
        if task_id not in cache:
            cache[task_id] = await task_belongs_to_tenant(task_store, task_id, tenant_id)
        if cache[task_id]:
            filtered.append(message)
    return filtered


async def require_task_for_tenant(
    task_store,
    task_id: str,
    tenant_id: str,
) -> TaskRecord | None:
    return await task_store.get(task_id, tenant_id=tenant_id)


async def tenant_id_for_task(task_store, task_id: str) -> str:
    if not task_id:
        return DEFAULT_TENANT_ID
    task = await task_store.get(task_id)
    return task.tenant_id if task else DEFAULT_TENANT_ID
