"""GitHub search tool — queries GitHub REST API for repositories."""

from __future__ import annotations

import logging

import httpx

from backend.config import settings
from backend.tools.base import Tool, ToolResult

logger = logging.getLogger(__name__)


class GitHubTool(Tool):
    name = "github"
    description = "Search open-source repositories on GitHub"

    async def run(self, query: str) -> ToolResult:
        try:
            headers = {"Accept": "application/vnd.github+json"}
            if settings.github_token:
                headers["Authorization"] = f"Bearer {settings.github_token}"

            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.get(
                    "https://api.github.com/search/repositories",
                    params={"q": query, "sort": "stars", "per_page": 5},
                    headers=headers,
                )
                response.raise_for_status()
                data = response.json()

            items = data.get("items", [])
            if not items:
                return ToolResult(self.name, True, f"No GitHub repos found for: {query}")

            lines = [f"【GitHub】{len(items)} repos found for «{query}»"]
            for idx, repo in enumerate(items, 1):
                lines.append(
                    f"{idx}. {repo['full_name']} ⭐ {repo['stargazers_count']}\n"
                    f"   {repo.get('description') or 'No description'}\n"
                    f"   Language: {repo.get('language') or 'N/A'}\n"
                    f"   URL: {repo['html_url']}"
                )
            return ToolResult(self.name, True, "\n".join(lines))
        except Exception as exc:
            logger.warning("GitHub tool failed: %s", exc)
            return ToolResult(self.name, False, f"GitHub search failed: {exc}")
