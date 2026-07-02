"""GitHub search tool — queries GitHub REST API for repositories."""

from __future__ import annotations

import logging

import httpx

from backend.config import settings
from backend.tools.base import Tool, ToolResult

logger = logging.getLogger(__name__)

_MAX_DESC_LEN = 240
_SPAM_HINTS = ("pdf下载", "百度云", "电子书", "网盘", "磁力", "torrent")


def _clean_text(text: str, *, limit: int = _MAX_DESC_LEN) -> str:
    cleaned = " ".join((text or "").split())
    if len(cleaned) > limit:
        cleaned = cleaned[:limit].rstrip() + "…"
    return cleaned


def _looks_spam(description: str) -> bool:
    lower = (description or "").lower()
    if len(description) > 500:
        return True
    return any(hint in lower for hint in _SPAM_HINTS)


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
            shown = 0
            for repo in items:
                description = _clean_text(repo.get("description") or "")
                if _looks_spam(description):
                    continue
                shown += 1
                lines.append(
                    f"{shown}. {repo['full_name']} ⭐ {repo['stargazers_count']}\n"
                    f"   {description or 'No description'}\n"
                    f"   Language: {repo.get('language') or 'N/A'}\n"
                    f"   URL: {repo['html_url']}"
                )
                if shown >= 5:
                    break
            if shown == 0:
                return ToolResult(
                    self.name,
                    True,
                    f"【GitHub】未找到可用仓库（检索词：{query}），请依据模型知识继续。",
                )
            return ToolResult(self.name, True, "\n".join(lines))
        except Exception as exc:
            logger.warning("GitHub tool failed: %s", exc)
            return ToolResult(self.name, False, f"GitHub search failed: {exc}")
