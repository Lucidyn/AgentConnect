"""Unit tests for plan DAG validation."""

from backend.core.plan_validate import validate_assignments
from backend.models.plan import TaskAssignment


def test_validate_rejects_duplicate_ids():
    assignments = [
        TaskAssignment(id="t1", agent="A", task="a"),
        TaskAssignment(id="t1", agent="B", task="b"),
    ]
    errors = validate_assignments(assignments)
    assert any("duplicate" in e for e in errors)


def test_validate_rejects_unknown_dependency():
    assignments = [
        TaskAssignment(id="t1", agent="A", task="a", depends_on=["missing"]),
    ]
    errors = validate_assignments(assignments)
    assert any("unknown id" in e for e in errors)


def test_validate_rejects_cycle():
    assignments = [
        TaskAssignment(id="t1", agent="A", task="a", depends_on=["t2"]),
        TaskAssignment(id="t2", agent="B", task="b", depends_on=["t1"]),
    ]
    errors = validate_assignments(assignments)
    assert any("cycle" in e for e in errors)
