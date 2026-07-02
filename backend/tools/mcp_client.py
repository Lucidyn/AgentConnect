"""MCP client — connect external MCP servers and register tools."""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from backend.tools.base import Tool, ToolResult

logger = logging.getLogger(__name__)


class McpJsonRpcClient:
    """Minimal MCP client over HTTP JSON-RPC (Streamable HTTP / single-endpoint)."""

    def __init__(
        self,
        url: str,
        *,
        timeout: float = 30.0,
        headers: dict[str, str] | None = None,
    ) -> None:
        self._url = url.rstrip("/")
        self._timeout = timeout
        self._headers = {"Content-Type": "application/json", **(headers or {})}
        self._seq = 0
        self._session_id: str | None = None

    def _next_id(self) -> int:
        self._seq += 1
        return self._seq

    async def request(self, method: str, params: dict | None = None) -> Any:
        payload = {
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": method,
            "params": params or {},
        }
        headers = dict(self._headers)
        if self._session_id:
            headers["Mcp-Session-Id"] = self._session_id
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.post(self._url, json=payload, headers=headers)
            response.raise_for_status()
            session_id = response.headers.get("Mcp-Session-Id")
            if session_id:
                self._session_id = session_id
            data = response.json()
        if "error" in data:
            err = data["error"]
            raise RuntimeError(err.get("message") or str(err))
        return data.get("result")

    async def initialize(self) -> None:
        await self.request(
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "agent-connect", "version": "1.2"},
            },
        )
        await self.request("notifications/initialized")

    async def list_tools(self) -> list[dict[str, Any]]:
        result = await self.request("tools/list")
        return list((result or {}).get("tools") or [])

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> str:
        result = await self.request("tools/call", {"name": name, "arguments": arguments})
        parts = (result or {}).get("content") or []
        chunks: list[str] = []
        for part in parts:
            if isinstance(part, dict) and part.get("type") == "text":
                chunks.append(str(part.get("text", "")))
        if chunks:
            return "\n".join(chunks)
        return json.dumps(result, ensure_ascii=False)


class McpProxyTool(Tool):
    """Expose one remote MCP tool through the platform ToolRegistry."""

    def __init__(
        self,
        server_name: str,
        tool_name: str,
        description: str,
        client: McpJsonRpcClient,
    ) -> None:
        self.name = f"{server_name}_{tool_name}"
        self.description = description or f"MCP tool {tool_name} from {server_name}"
        self._tool_name = tool_name
        self._client = client

    async def run(self, query: str) -> ToolResult:
        try:
            text = await self._client.call_tool(self._tool_name, {"query": query})
            return ToolResult(self.name, True, text)
        except Exception as exc:
            logger.warning("MCP tool %s failed: %s", self.name, exc)
            return ToolResult(self.name, False, str(exc))


async def register_mcp_server(registry: ToolRegistry, entry: dict[str, Any]) -> int:
    name = str(entry.get("name") or "mcp").strip()
    url = str(entry.get("url") or entry.get("server_url") or "").strip()
    if not url:
        logger.warning("MCP server %s has no url — skipping", name)
        return 0
    prefix = str(entry.get("prefix") or name).strip()
    timeout = float(entry.get("timeout", 30))
    headers = entry.get("headers") or {}
    client = McpJsonRpcClient(url, timeout=timeout, headers=headers)
    try:
        await client.initialize()
        tools = await client.list_tools()
        count = 0
        for tool in tools:
            tool_name = str(tool.get("name") or "").strip()
            if not tool_name:
                continue
            registry.register(
                McpProxyTool(
                    prefix,
                    tool_name,
                    str(tool.get("description") or ""),
                    client,
                )
            )
            count += 1
        logger.info("Registered %d MCP tool(s) from server %s", count, name)
        return count
    except Exception as exc:
        logger.warning("Failed to connect MCP server %s: %s", name, exc)
        return 0
