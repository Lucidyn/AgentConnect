"""Shared constants — avoid magic strings and duplicated limits."""

MAX_PROCESSED_MESSAGE_IDS = 2000

# Built-in agent names (stable protocol identifiers)
PLANNER = "Planner"
CODER = "Coder"
RESEARCH = "Research"
REVIEWER = "Reviewer"
VISION = "Vision"
TEST_RUNNER = "TestRunner"
WRITER = "Writer"
ANALYST = "Analyst"
TRANSLATOR = "Translator"

# Agents that only gate quality — not reset targets for content retry loops
GATE_AGENTS = frozenset({REVIEWER, TEST_RUNNER})
CONTENT_AGENTS = frozenset({CODER, RESEARCH, WRITER, ANALYST, VISION, TRANSLATOR})
