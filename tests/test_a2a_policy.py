"""A2A in-process policy tests."""

from backend.core.a2a_policy import A2A_MAX_QUERIES, check_a2a_query, record_a2a_query


def test_allowed_pair_passes():
    assert check_a2a_query("Coder", "Research", {}) is None


def test_disallowed_pair_rejected():
    assert check_a2a_query("Planner", "Research", {}) is not None


def test_query_limit_enforced():
    ctx = {"a2a_query_count": A2A_MAX_QUERIES}
    assert check_a2a_query("Coder", "Research", ctx) is not None


def test_record_increments_counter():
    updated = record_a2a_query({"a2a_query_count": 1})
    assert updated["a2a_query_count"] == 2
