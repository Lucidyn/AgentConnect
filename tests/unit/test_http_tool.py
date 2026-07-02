"""HTTP tool plugin tests."""

from __future__ import annotations

import pytest

from backend.tools.http import HttpTool


@pytest.mark.asyncio
async def test_http_tool_requires_base_url():
    tool = HttpTool()
    tool.configure({})
    result = await tool.run("query")
    assert result.success is False
    assert "not configured" in result.content.lower()


@pytest.mark.asyncio
async def test_http_tool_get(monkeypatch):
    tool = HttpTool()
    tool.configure({"base_url": "https://example.com", "path": "/search"})

    class FakeResponse:
        text = '{"ok": true}'
        def raise_for_status(self):
            return None

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def get(self, url, params=None):
            assert "example.com/search" in url
            assert params["q"] == "test"
            return FakeResponse()

    monkeypatch.setattr("backend.tools.http.httpx.AsyncClient", lambda **kwargs: FakeClient())
    result = await tool.run("test")
    assert result.success is True
    assert "ok" in result.content
