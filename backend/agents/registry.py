"""Built-in agent class registry — single source for plugin loader."""

from __future__ import annotations

from backend.agents.analyst import AnalystAgent
from backend.agents.coder import CoderAgent
from backend.agents.planner import PlannerAgent
from backend.agents.research import ResearchAgent
from backend.agents.reviewer import ReviewerAgent
from backend.agents.test_runner import TestRunnerAgent
from backend.agents.translator import TranslatorAgent
from backend.agents.writer import WriterAgent
from backend.core.agent import Agent

BUILTIN_AGENTS: dict[str, type[Agent]] = {
    "planner": PlannerAgent,
    "research": ResearchAgent,
    "coder": CoderAgent,
    "writer": WriterAgent,
    "analyst": AnalystAgent,
    "translator": TranslatorAgent,
    "test_runner": TestRunnerAgent,
    "reviewer": ReviewerAgent,
}
