"""Summarizer — OpenAI Agents SDK example plugin."""

from __future__ import annotations

from backend.core.bridged_agent import OpenAIAgentsBridge


class SummarizerAgent(OpenAIAgentsBridge):
    name = "Summarizer"
    role = "summarizer"
    capabilities = ["summarization", "text_processing"]
    description = "OpenAI Agents SDK 示例：文本摘要"
    instructions = "Summarize the user task in 3 bullet points. Be concise."
