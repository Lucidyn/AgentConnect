"""Tool registry — MCP-inspired tool discovery and execution."""

from __future__ import annotations

import logging

from backend.tools.arxiv import ArxivTool
from backend.tools.base import Tool, ToolResult
from backend.tools.github import GitHubTool

logger = logging.getLogger(__name__)

_ARXIV_HINTS = ("论文", "paper", "arxiv", "research", "学术", "期刊")
_GITHUB_HINTS = ("github", "开源", "repo", "repository", "代码库", "项目")


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool
        logger.info("Registered tool: %s", tool.name)

    def list_tools(self) -> list[dict[str, str]]:
        return [{"name": t.name, "description": t.description} for t in self._tools.values()]

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    async def run(self, name: str, query: str) -> ToolResult:
        tool = self._tools.get(name)
        if not tool:
            return ToolResult(name, False, f"Unknown tool: {name}")
        return await tool.run(query)

    def select_for_task(self, task: str) -> list[str]:
        task_lower = task.lower()
        selected: list[str] = []
        if any(hint in task_lower for hint in _ARXIV_HINTS):
            selected.append("arxiv")
        if any(hint in task_lower for hint in _GITHUB_HINTS):
            selected.append("github")
        if not selected:
            selected = ["arxiv", "github"]
        return [name for name in selected if name in self._tools]

    async def run_for_task(self, task: str) -> list[ToolResult]:
        results: list[ToolResult] = []
        for name in self.select_for_task(task):
            result = await self.run(name, task)
            results.append(result)
        return results


def create_tool_registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(ArxivTool())
    registry.register(GitHubTool())
    return registry
