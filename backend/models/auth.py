"""Authentication and authorization models."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


DEFAULT_TENANT_ID = "default"


class Role(str, Enum):
    VIEWER = "viewer"
    OPERATOR = "operator"
    ADMIN = "admin"


_ROLE_ORDER = {
    Role.VIEWER: 0,
    Role.OPERATOR: 1,
    Role.ADMIN: 2,
}


class AuthContext(BaseModel):
    tenant_id: str = DEFAULT_TENANT_ID
    role: Role = Role.ADMIN
    key_id: str = ""
    user_id: str = ""

    def can(self, min_role: Role) -> bool:
        return _ROLE_ORDER[self.role] >= _ROLE_ORDER[min_role]

    def require(self, min_role: Role) -> None:
        if not self.can(min_role):
            from fastapi import HTTPException

            raise HTTPException(status_code=403, detail="Insufficient permissions")
