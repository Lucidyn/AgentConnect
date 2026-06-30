"""Shared text helpers."""

from __future__ import annotations

import re

_TOKEN_PATTERN = re.compile(r"[a-zA-Z0-9\u4e00-\u9fff]+")


def tokenize_words(text: str) -> list[str]:
    return _TOKEN_PATTERN.findall(text.lower())


def tokenize_set(text: str) -> set[str]:
    return set(tokenize_words(text))
