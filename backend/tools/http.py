"""HTTP fetch tool — MCP-style external data plugin."""

from __future__ import annotations

import httpx

from backend.config import settings
from backend.tools.base import Tool, ToolResult


class HttpTool(Tool):
    name = "http"
    description = "Fetch text/JSON from a configured HTTP endpoint (plugin/MCP style)"

    def __init__(self) -> None:
        self._base_url = ""
        self._path = "/"
        self._method = "GET"

    def configure(self, config: dict) -> None:
        self._base_url = str(config.get("base_url") or settings.http_tool_base_url or "").strip()
        self._path = str(config.get("path") or "/")
        self._method = str(config.get("method") or "GET").upper()

    async def run(self, query: str) -> ToolResult:
        base = self._base_url.rstrip("/")
        if not base:
            return ToolResult(
                self.name,
                False,
                "HTTP tool not configured — set base_url in manifest or HTTP_TOOL_BASE_URL",
            )
        url = f"{base}{self._path if self._path.startswith('/') else '/' + self._path}"
        try:
            async with httpx.AsyncClient(timeout=12.0, follow_redirects=True) as client:
                if self._method == "POST":
                    response = await client.post(url, json={"query": query})
                else:
                    response = await client.get(url, params={"q": query})
                response.raise_for_status()
                text = response.text[:8000]
                return ToolResult(self.name, True, text)
        except Exception as exc:
            return ToolResult(self.name, False, f"HTTP tool error: {exc}")
