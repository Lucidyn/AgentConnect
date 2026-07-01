"""Arxiv search tool — queries export.arxiv.org API."""

from __future__ import annotations

import logging
import re
import xml.etree.ElementTree as ET

import httpx

from backend.config import settings
from backend.tools.base import Tool, ToolResult

logger = logging.getLogger(__name__)

ATOM_NS = {"atom": "http://www.w3.org/2005/Atom"}


class ArxivTool(Tool):
    name = "arxiv"
    description = "Search academic papers on Arxiv"

    async def run(self, query: str) -> ToolResult:
        timeout = max(2.0, settings.arxiv_timeout_seconds)
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.get(
                    "https://export.arxiv.org/api/query",
                    params={"search_query": f"all:{query}", "max_results": 3},
                    follow_redirects=True,
                )
                response.raise_for_status()
            papers = self._parse_feed(response.text)
            if not papers:
                return ToolResult(self.name, True, f"No Arxiv papers found for: {query}")
            lines = [f"【Arxiv】{len(papers)} papers found for «{query}»"]
            for idx, paper in enumerate(papers, 1):
                lines.append(
                    f"{idx}. {paper['title']}\n"
                    f"   Authors: {paper['authors']}\n"
                    f"   Published: {paper['published']}\n"
                    f"   Link: {paper['link']}\n"
                    f"   Summary: {paper['summary'][:200]}..."
                )
            return ToolResult(self.name, True, "\n".join(lines))
        except httpx.TimeoutException:
            logger.warning("Arxiv tool timed out after %ss", timeout)
            return ToolResult(
                self.name,
                True,
                f"【Arxiv】检索超时（{timeout:.0f}s），已跳过论文搜索，请依据 GitHub 与模型知识继续。",
            )
        except Exception as exc:
            logger.warning("Arxiv tool failed: %s", exc)
            return ToolResult(
                self.name,
                True,
                f"【Arxiv】暂不可用（{exc}），已跳过论文搜索。",
            )

    def _parse_feed(self, xml_text: str) -> list[dict[str, str]]:
        root = ET.fromstring(xml_text)
        papers: list[dict[str, str]] = []
        for entry in root.findall("atom:entry", ATOM_NS):
            title = self._clean(entry.findtext("atom:title", default="", namespaces=ATOM_NS))
            summary = self._clean(entry.findtext("atom:summary", default="", namespaces=ATOM_NS))
            published = entry.findtext("atom:published", default="", namespaces=ATOM_NS)[:10]
            authors = ", ".join(
                author.findtext("atom:name", default="", namespaces=ATOM_NS)
                for author in entry.findall("atom:author", ATOM_NS)
            )
            link = ""
            for link_el in entry.findall("atom:link", ATOM_NS):
                if link_el.attrib.get("type") == "text/html":
                    link = link_el.attrib.get("href", "")
                    break
            papers.append(
                {
                    "title": title,
                    "authors": authors,
                    "published": published,
                    "link": link,
                    "summary": summary,
                }
            )
        return papers

    @staticmethod
    def _clean(text: str) -> str:
        return re.sub(r"\s+", " ", text).strip()
