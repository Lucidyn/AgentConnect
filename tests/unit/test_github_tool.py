import pytest

from backend.tools.github import GitHubTool, _looks_spam
from backend.tools.registry import ToolRegistry


def test_looks_spam_detects_long_or_keyword_descriptions():
    assert _looks_spam("PDF下载 百度云 电子书")
    assert _looks_spam("x" * 600)
    assert not _looks_spam("YOLO object detection in PyTorch")


@pytest.mark.asyncio
async def test_github_skips_spam_repos(monkeypatch):
    tool = GitHubTool()

    async def fake_get(*args, **kwargs):
        class Resp:
            def raise_for_status(self):
                return None

            def json(self):
                return {
                    "items": [
                        {
                            "full_name": "spam/repo",
                            "stargazers_count": 1,
                            "description": "PDF下载 百度云 " + ("x" * 800),
                            "language": "Python",
                            "html_url": "https://github.com/spam/repo",
                        },
                        {
                            "full_name": "good/hotel-guide",
                            "stargazers_count": 10,
                            "description": "Tips for choosing hotels by location and reviews.",
                            "language": "Markdown",
                            "html_url": "https://github.com/good/hotel-guide",
                        },
                    ]
                }

        return Resp()

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        get = fake_get

    monkeypatch.setattr("backend.tools.github.httpx.AsyncClient", lambda **kwargs: FakeClient())
    result = await tool.run("hotel selection guide")
    assert result.success
    assert "good/hotel-guide" in result.content
    assert "PDF下载" not in result.content


def test_select_for_task_skips_tools_for_general_life_queries():
    registry = ToolRegistry()
    registry.register(GitHubTool())
    assert registry.select_for_task("如何挑选酒店住宿") == []
