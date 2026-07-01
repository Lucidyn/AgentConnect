"""Database backends — SQLite (dev) and PostgreSQL (multi-replica production)."""

from backend.core.db.base import Database, create_database

__all__ = ["Database", "create_database"]
