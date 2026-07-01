"""Detect task domain for plan template selection."""

from __future__ import annotations

from enum import Enum


class TaskDomain(str, Enum):
    CODING = "coding"
    WRITING = "writing"
    ANALYSIS = "analysis"
    RESEARCH = "research"
    GENERAL = "general"


_CODING_KEYWORDS = (
    "code",
    "coding",
    "api",
    "implement",
    "python",
    "fastapi",
    "docker",
    "deploy",
    "bug",
    "refactor",
    "实现",
    "编码",
    "代码",
    "接口",
    "部署",
)

_WRITING_KEYWORDS = (
    "write",
    "writing",
    "article",
    "blog",
    "copy",
    "content",
    "essay",
    "post",
    "文案",
    "写作",
    "文章",
    "内容",
    "稿件",
    "营销",
)

_ANALYSIS_KEYWORDS = (
    "analyze",
    "analysis",
    "compare",
    "evaluation",
    "assessment",
    "report",
    "insight",
    "分析",
    "评估",
    "对比",
    "报告",
    "洞察",
)

_RESEARCH_KEYWORDS = (
    "research",
    "survey",
    "literature",
    "paper",
    "arxiv",
    "调研",
    "研究",
    "论文",
    "资料",
)


def detect_task_domain(task: str) -> TaskDomain:
    lower = task.lower()
    scores = {
        TaskDomain.CODING: _score(lower, _CODING_KEYWORDS),
        TaskDomain.WRITING: _score(lower, _WRITING_KEYWORDS),
        TaskDomain.ANALYSIS: _score(lower, _ANALYSIS_KEYWORDS),
        TaskDomain.RESEARCH: _score(lower, _RESEARCH_KEYWORDS),
    }
    best = max(scores.items(), key=lambda item: item[1])
    if best[1] == 0:
        return TaskDomain.GENERAL
    if scores[TaskDomain.CODING] == best[1]:
        return TaskDomain.CODING
    if scores[TaskDomain.WRITING] == best[1]:
        return TaskDomain.WRITING
    if scores[TaskDomain.ANALYSIS] == best[1]:
        return TaskDomain.ANALYSIS
    return TaskDomain.RESEARCH


def _score(text: str, keywords: tuple[str, ...]) -> int:
    return sum(1 for keyword in keywords if keyword in text)
