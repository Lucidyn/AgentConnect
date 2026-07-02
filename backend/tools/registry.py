"""Tool registry — MCP-inspired tool discovery and execution."""

from __future__ import annotations

import asyncio
import logging

from backend.tools.arxiv import ArxivTool
from backend.tools.base import Tool, ToolResult
from backend.tools.github import GitHubTool

logger = logging.getLogger(__name__)

_ARXIV_HINTS = ("论文", "paper", "arxiv", "research", "学术", "期刊")
_GITHUB_HINTS = ("github", "开源", "repo", "repository", "项目", "库", "implement", "code")
_HTTP_HINTS = ("http://", "https://", "api ", "endpoint", "fetch ", "请求", "接口")


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
        from backend.core.otel import start_tool_span

        with start_tool_span(name):
            return await tool.run(query)

    def select_for_task(self, task: str) -> list[str]:
        task_lower = task.lower()
        selected: list[str] = []
        if any(hint in task_lower for hint in _ARXIV_HINTS):
            selected.append("arxiv")
        if any(hint in task_lower for hint in _GITHUB_HINTS):
            selected.append("github")
        if any(hint in task_lower for hint in _HTTP_HINTS) and "http" in self._tools:
            selected.append("http")
        if not selected:
            selected = ["github", "arxiv"]
        return [name for name in selected if name in self._tools]

    async def run_for_task(self, task: str) -> list[ToolResult]:
        names = self.select_for_task(task)
        if not names:
            return []
        results = await asyncio.gather(
            *[self.run(name, task) for name in names],
            return_exceptions=True,
        )
        out: list[ToolResult] = []
        for name, result in zip(names, results):
            if isinstance(result, Exception):
                logger.warning("Tool %s raised: %s", name, result)
                out.append(
                    ToolResult(
                        name,
                        True,
                        f"【{name}】执行异常，已跳过（{result}）。",
                    )
                )
            else:
                out.append(result)
        return out


def create_tool_registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(ArxivTool())
    registry.register(GitHubTool())
    return registry
