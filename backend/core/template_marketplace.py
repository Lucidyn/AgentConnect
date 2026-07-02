"""Public template marketplace — shared read-only DAG templates."""

from __future__ import annotations

import json
import logging
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backend.config import settings
from backend.core.saved_templates import save_template

logger = logging.getLogger(__name__)


def _market_dir() -> Path:
    path = Path(settings.template_marketplace_dir)
    path.mkdir(parents=True, exist_ok=True)
    return path


def list_marketplace() -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for path in sorted(_market_dir().glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            items.append(
                {
                    "id": path.stem,
                    "name": data.get("name", path.stem),
                    "description": data.get("description", ""),
                    "assignment_count": len(data.get("plan", {}).get("assignments", [])),
                    "source": "marketplace",
                    "updated_at": data.get("updated_at"),
                }
            )
        except Exception as exc:
            logger.warning("Skip invalid marketplace template %s: %s", path, exc)
    return items


def get_marketplace(template_id: str) -> dict[str, Any] | None:
    path = _market_dir() / f"{template_id}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def publish_to_marketplace(
    *,
    template_id: str,
    name: str,
    plan: dict[str, Any],
    description: str = "",
) -> dict[str, Any]:
    payload = {
        "id": template_id,
        "name": name,
        "description": description,
        "plan": plan,
        "source": "marketplace",
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    path = _market_dir() / f"{template_id}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def fork_marketplace_template(template_id: str, tenant_id: str) -> dict[str, Any] | None:
    source = get_marketplace(template_id)
    if not source:
        return None
    return save_template(
        name=source.get("name", template_id),
        description=f"Forked from marketplace:{template_id}",
        plan=source.get("plan") or {},
        tenant_id=tenant_id,
    )


def export_saved_template(template_id: str, tenant_id: str) -> dict[str, Any] | None:
    from backend.core.saved_templates import get_saved

    saved = get_saved(template_id, tenant_id=tenant_id)
    if not saved:
        return None
    return {
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "template": saved,
    }


def import_template_payload(payload: dict[str, Any], tenant_id: str) -> dict[str, Any]:
    template = payload.get("template") or payload
    plan = template.get("plan") or template.get("custom_plan") or {}
    return save_template(
        name=template.get("name", "imported"),
        description=template.get("description", "Imported template"),
        plan=plan,
        tenant_id=tenant_id,
    )
