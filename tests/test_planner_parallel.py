"""Planner parallel scheduling and human-in-the-loop tests."""

from backend.models.plan import AssignmentStatus, TaskAssignment, TaskPlan


def test_mark_done_by_assignment_id():
    plan = TaskPlan(
        assignments=[
            TaskAssignment(id="t1", agent="Research", task="a", status=AssignmentStatus.RUNNING),
            TaskAssignment(id="t2", agent="Research", task="b", status=AssignmentStatus.PENDING),
        ]
    )
    done = plan.mark_done(assignment_id="t1")
    assert done is not None
    assert done.id == "t1"
    assert plan.assignments[1].status == AssignmentStatus.PENDING


def test_mark_done_pending_assignment_by_id():
    """Agent may finish before RUNNING status is persisted — trust assignment_id."""
    plan = TaskPlan(
        assignments=[
            TaskAssignment(id="t2", agent="Coder", task="c", status=AssignmentStatus.PENDING),
        ]
    )
    done = plan.mark_done(assignment_id="t2")
    assert done is not None
    assert done.status == AssignmentStatus.DONE


def test_parallel_pending_ready():
    plan = TaskPlan(
        assignments=[
            TaskAssignment(id="t1", agent="Research", task="a", depends_on=[]),
            TaskAssignment(id="t2", agent="Vision", task="b", depends_on=[]),
            TaskAssignment(id="t3", agent="Coder", task="c", depends_on=["t1", "t2"]),
        ]
    )
    ready = plan.pending_ready()
    assert {a.id for a in ready} == {"t1", "t2"}

    plan.assignments[0].status = AssignmentStatus.RUNNING
    plan.mark_done(assignment_id="t1")
    assert plan.pending_ready()[0].id == "t2"

    plan.assignments[1].status = AssignmentStatus.RUNNING
    plan.mark_done(assignment_id="t2")
    assert plan.pending_ready()[0].id == "t3"
