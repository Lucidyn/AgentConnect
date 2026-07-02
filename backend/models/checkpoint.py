"""Assignment-level checkpoint snapshots for replay."""

from __future__ import annotations

from pydantic import BaseModel, Field


class CheckpointSnapshot(BaseModel):
    id: str
    assignment_id: str
    label: str = ""
    created_at: str = ""
    plan: dict = Field(default_factory=dict)
    results: dict[str, str] = Field(default_factory=dict)
