"""Per-task runtime context — isolated from Agent in-memory state."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from backend.constants import (
    ANALYST,
    CODER,
    CONTENT_AGENTS,
    RESEARCH,
    TRANSLATOR,
    VISION,
    WRITER,
)
from backend.core.llm_usage import LLMUsageEntry
from backend.models.checkpoint import CheckpointSnapshot
from backend.models.plan import TaskAssignment, TaskPlan

_MAX_RESULT_CHARS = 12000


class LoopState(BaseModel):
    iteration: int = 0
    max_iterations: int = 3
    feedback: str = ""
    status: str = "running"  # running | passed | failed


class BlackboardEntry(BaseModel):
    author: str = ""
    entry_type: str = "fact"  # fact | question | decision
    content: str = ""
    thread_id: str = ""
    created_at: datetime | None = None


class WorkspaceState(BaseModel):
    facts: list[str] = []
    decisions: list[str] = []
    open_questions: list[str] = []
    blockers: list[str] = []
    artifacts: list[str] = []
    entries: list[BlackboardEntry] = Field(default_factory=list)
    negotiation_log: list[str] = Field(default_factory=list)


class NegotiationState(BaseModel):
    round: int = 0
    max_rounds: int = 2
    resolved: list[dict] = Field(default_factory=list)


class TaskContext(BaseModel):
    template_id: str = ""
    custom_plan: dict | None = None
    collaboration_mode: str = "planner"  # planner | blackboard
    negotiation: bool = False
    negotiation_state: NegotiationState = Field(default_factory=NegotiationState)
    research_result: str = ""
    coder_result: str = ""
    vision_result: str = ""
    writer_result: str = ""
    analyst_result: str = ""
    translator_result: str = ""
    results: dict[str, str] = {}
    approval_message: str = ""
    approval_assignment_id: str = ""
    processed_message_ids: list[str] = []
    assignment_retries: dict[str, int] = {}
    retry_feedback: str = ""
    loops: dict[str, LoopState] = {}
    workspace: WorkspaceState = WorkspaceState()
    llm_usage: list[LLMUsageEntry] = Field(default_factory=list)
    assignment_started_at: dict[str, str] = Field(default_factory=dict)
    checkpoints: list[CheckpointSnapshot] = Field(default_factory=list)
    a2a_query_count: int = 0
    pending_downstream: bool = False
    workspace_path: str = ""
    workspace_write_enabled: bool = True
    workspace_files_written: list[str] = Field(default_factory=list)

    def record_result(self, assignment: TaskAssignment, content: str) -> None:
        """Store assignment output and sync legacy named fields."""
        if len(content) > _MAX_RESULT_CHARS:
            content = content[:_MAX_RESULT_CHARS].rstrip() + "\n…（输出已截断）"
        self.results[assignment.id] = content
        if assignment.agent == RESEARCH:
            self.research_result = content
            self.workspace.facts.append(content[:500])
        elif assignment.agent == CODER:
            self.coder_result = content
            self.retry_feedback = ""
            loop = self.loops.get(assignment.id)
            if loop:
                loop.status = "passed"
                self.loops[assignment.id] = loop
        elif assignment.agent == WRITER:
            self.writer_result = content
            self.retry_feedback = ""
        elif assignment.agent == ANALYST:
            self.analyst_result = content
            self.retry_feedback = ""
        elif assignment.agent == TRANSLATOR:
            self.translator_result = content
            self.retry_feedback = ""
        elif assignment.agent == VISION:
            self.vision_result = content
        elif assignment.agent == "TestRunner" and "FAILED" in content:
            self.workspace.blockers.append(content)

    def coder_output(self, plan: TaskPlan | None = None) -> str:
        return self.primary_output(plan)

    def primary_output(self, plan: TaskPlan | None = None) -> str:
        """Return the latest primary deliverable (code, draft, report, etc.)."""
        if plan:
            for assignment in reversed(plan.assignments):
                if assignment.agent in CONTENT_AGENTS and assignment.id in self.results:
                    return self.results[assignment.id]
        for value in (
            self.translator_result,
            self.coder_result,
            self.writer_result,
            self.analyst_result,
            self.research_result,
        ):
            if value:
                return value
        return ""

    @staticmethod
    def plan_from_record(plan_data: dict | None) -> TaskPlan | None:
        return TaskPlan.from_record(plan_data)
