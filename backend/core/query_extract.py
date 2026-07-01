"""Extract search keywords and version hints from user task text."""

from __future__ import annotations

import re

_YOLO_VERSION = re.compile(r"(?i)yolo(?:\s*-?\s*v)?\s*(\d+)")
_QWEN = re.compile(r"(?i)qwen[\w.-]*")
_PADDLE = re.compile(r"(?i)paddleocr[\w.-]*|paddle[\s-]?ocr")
_ENGLISH_TOKEN = re.compile(r"[A-Za-z][A-Za-z0-9+._-]*")

_TASK_PREFIXES = (
    "调研：",
    "调研:",
    "查一下",
    "查 ",
    "实现：",
    "实现:",
    "写作：",
    "写作:",
)


def extract_yolo_version(task: str) -> str | None:
    match = _YOLO_VERSION.search(task)
    return match.group(1) if match else None


def yolo_model_name(task: str, *, default_version: str = "11") -> str:
    version = extract_yolo_version(task) or default_version
    return f"yolo{version}n.pt"


def extract_tool_query(task: str) -> str:
    """Build a search query that preserves version numbers (e.g. YOLO26)."""
    text = task.strip()
    for prefix in _TASK_PREFIXES:
        if text.startswith(prefix):
            text = text[len(prefix) :].strip()
            break

    clause = text.split("，")[0].split(",")[0].strip()

    yolo = _YOLO_VERSION.search(clause)
    if yolo:
        return f"YOLO{yolo.group(1)}"

    for pattern in (_QWEN, _PADDLE):
        match = pattern.search(clause)
        if match:
            return match.group(0)

    tokens = _ENGLISH_TOKEN.findall(clause)
    if tokens:
        # Join adjacent alnum tokens like "YOLO" + "26" when user typed with a space.
        merged: list[str] = []
        for token in tokens:
            if merged and re.fullmatch(r"\d+", token) and re.search(r"[A-Za-z]$", merged[-1]):
                merged[-1] = merged[-1] + token
            else:
                merged.append(token)
        return merged[0]

    return clause or task
