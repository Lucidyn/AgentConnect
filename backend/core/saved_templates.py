"""User-saved plan templates (simple JSON files on disk)."""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backend.config import settings

logger = logging.getLogger(__name__)


def _saved_dir() -> Path:
    path = Path(settings.saved_templates_dir)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _slug(name: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "-", name.strip()).strip("-").lower()
    return slug[:48] or "template"


def list_saved() -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for path in sorted(_saved_dir().glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            items.append(
                {
                    "id": path.stem,
                    "name": data.get("name", path.stem),
                    "description": data.get("description", ""),
                    "assignment_count": len(data.get("plan", {}).get("assignments", [])),
                    "updated_at": data.get("updated_at"),
                    "source": "saved",
                }
            )
        except Exception as exc:
            logger.warning("Skip invalid saved template %s: %s", path, exc)
    return items


def get_saved(template_id: str) -> dict[str, Any] | None:
    path = _saved_dir() / f"{template_id}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def save_template(*, name: str, plan: dict[str, Any], description: str = "") -> dict[str, Any]:
    template_id = _slug(name)
    base = template_id
    counter = 2
    while (_saved_dir() / f"{template_id}.json").exists():
        template_id = f"{base}-{counter}"
        counter += 1
    payload = {
        "id": template_id,
        "name": name.strip() or template_id,
        "description": description.strip(),
        "plan": plan,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    path = _saved_dir() / f"{template_id}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def delete_saved(template_id: str) -> bool:
    path = _saved_dir() / f"{template_id}.json"
    if not path.exists():
        return False
    path.unlink()
    return True
