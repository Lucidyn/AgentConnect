"""Tenant budget checks and spend tracking."""

from __future__ import annotations

from backend.config import settings
from backend.core.llm_usage import LLMUsageEntry, estimate_cost


async def check_submit_budget(tenant_store, tenant_id: str) -> str | None:
    """Return error message if tenant is over budget, else None."""
    if not settings.tenant_budget_enabled:
        return None
    budget = await tenant_store.get_budget_usd(tenant_id)
    if budget is None or budget <= 0:
        return None
    spent = await tenant_store.get_spent_usd(tenant_id)
    if spent >= budget:
        return f"Tenant budget exceeded (${spent:.4f} / ${budget:.4f})"
    return None


async def record_usage_spend(tenant_store, tenant_id: str, entry: LLMUsageEntry) -> None:
    if not settings.tenant_budget_enabled:
        return
    cost = estimate_cost(entry)
    if cost > 0:
        await tenant_store.add_spent_usd(tenant_id, cost)
