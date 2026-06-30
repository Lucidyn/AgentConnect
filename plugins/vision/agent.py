"""Vision Agent — example external plugin (rule-based demo)."""

from __future__ import annotations

from backend.constants import PLANNER
from backend.core.agent import Agent
from backend.models.message import Message, MessageType


class VisionAgent(Agent):
    name = "Vision"
    role = "vision"
    capabilities = ["image_analysis", "ocr", "object_detection"]
    description = "图像分析与 OCR 示例插件"

    async def think(self, message: Message) -> str | None:
        if message.message_type not in (MessageType.TASK, MessageType.RESPONSE):
            return None
        if message.from_agent not in (PLANNER, "User"):
            return None

        task = message.content[:300]
        model = self.plugin_config.get("llm_model", "PaddleOCR + YOLO")
        result = (
            f"[Vision 分析]\n"
            f"任务: {task}\n"
            f"建议方案: 使用 {model} 构建检测与 OCR 流水线\n"
            f"输出: 结构化 JSON（bbox + text + confidence）"
        )
        if message.from_agent == PLANNER:
            await self.reply_to_planner(message, result)
            return None
        return result
