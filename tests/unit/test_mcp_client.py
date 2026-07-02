"""MCP client unit tests."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from backend.tools.mcp_client import McpProxyTool, register_mcp_server
from backend.tools.registry import ToolRegistry


@pytest.mark.asyncio
async def test_mcp_proxy_tool_success():
    client = AsyncMock()
    client.call_tool = AsyncMock(return_value="mcp-result")
    tool = McpProxyTool("demo", "fetch", "fetch data", client)
    result = await tool.run("hello")
    assert result.success is True
    assert result.content == "mcp-result"
    client.call_tool.assert_awaited_once_with("fetch", {"query": "hello"})


@pytest.mark.asyncio
async def test_mcp_proxy_tool_failure():
    client = AsyncMock()
    client.call_tool = AsyncMock(side_effect=RuntimeError("connection refused"))
    tool = McpProxyTool("demo", "fetch", "fetch data", client)
    result = await tool.run("hello")
    assert result.success is False
    assert "connection refused" in result.content


@pytest.mark.asyncio
async def test_register_mcp_server():
    registry = ToolRegistry()
    entry = {"name": "demo", "url": "http://127.0.0.1:9999/mcp", "prefix": "demo"}

    with patch("backend.tools.mcp_client.McpJsonRpcClient") as client_cls:
        client = AsyncMock()
        client.initialize = AsyncMock()
        client.list_tools = AsyncMock(
            return_value=[{"name": "fetch", "description": "Fetch URL"}]
        )
        client_cls.return_value = client

        count = await register_mcp_server(registry, entry)

    assert count == 1
    assert registry.get("demo_fetch") is not None
