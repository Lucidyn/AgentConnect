"""Coder Agent — reads shared memory for cross-agent context."""

from __future__ import annotations

import re

from backend.constants import PLANNER
from backend.core.agent import Agent
from backend.core.query_extract import yolo_model_name
from backend.models.message import Message, MessageType

SYSTEM_PROMPT = """你是 Coder Agent。只输出：
1. 核心 Python 代码块（FastAPI 服务必须包含 GET /health 健康检查端点）
2. 一行运行方式
不要长篇解释。
若用户指定 YOLO 版本（如 YOLO26），模型权重须对应该版本（如 yolo26n.pt），不得改用 YOLOv6 或其他版本。"""

_HEALTH_SNIPPET = (
    "\n\n@app.get('/health')\ndef health():\n"
    "    return {'status': 'ok'}\n"
)


class CoderAgent(Agent):
    name = "Coder"
    role = "developer"
    capabilities = ["coding", "python", "docker", "api_development"]
    description = "编写代码、实现功能、生成部署配置"
    inputs = ["research_report", "review_feedback", "test_result"]
    outputs = ["code_patch", "implementation_notes"]
    accepts = ["assignment_start", "retry_request", "agent_query"]

    async def think(self, message: Message) -> str | None:
        task = message.content

        if "调研结果" in task:
            self.remember("research_context", task)

        shared = await self.recall_shared(task)
        research = self.recall("research_context", "")
        context_parts = [p for p in (research, shared) if p]
        context = "\n\n".join(context_parts)

        fallback = self._mock_code(task)
        result = await self.llm_chat(
            SYSTEM_PROMPT,
            f"背景：\n{context}\n\n编码任务：{task}" if context else f"编码任务：{task}",
            fallback,
            role=self.role,
            stream=True,
            message=message,
        )
        result = self._ensure_health_endpoint(result)

        await self.shared_memory.store(
            content=result,
            agent=self.name,
            metadata={"task": task[:200]},
            task_id=self._current_task_id,
        )
        self.remember("last_code", result)

        if message.from_agent == PLANNER:
            await self.reply_to_planner(message, result)
            return None

        return result

    @staticmethod
    def _ensure_health_endpoint(code: str) -> str:
        lower = code.lower()
        if "fastapi" not in lower:
            return code
        if "/health" in lower or "health()" in lower:
            return code
        if "```" in code:
            return re.sub(
                r"(```(?:python)?\n)([\s\S]*?)(```)",
                lambda m: m.group(1) + m.group(2).rstrip() + _HEALTH_SNIPPET + m.group(3),
                code,
                count=1,
            )
        return code.rstrip() + _HEALTH_SNIPPET

    def _mock_code(self, task: str) -> str:
        task_lower = task.lower()
        if "ocr" in task_lower or "paddle" in task_lower:
            return self._fixed_code()
        if "yolo" in task_lower:
            model_file = yolo_model_name(task)
            return (
                "```python\nfrom fastapi import FastAPI, UploadFile\n"
                "from ultralytics import YOLO\n\n"
                f'app = FastAPI()\nmodel = YOLO("{model_file}")\n\n'
                "@app.get('/health')\ndef health():\n"
                "    return {'status': 'ok'}\n\n"
                "@app.post('/detect')\nasync def detect(file: UploadFile):\n"
                "    return {'detections': model(await file.read())[0].tojson()}\n```"
            )
        return (
            f"```python\n# {task[:60]}\nfrom fastapi import FastAPI\n\n"
            "app = FastAPI()\n\n"
            "@app.get('/health')\ndef health():\n"
            "    return {'status': 'ok'}\n```"
        )

    def _fixed_code(self) -> str:
        return '''```python
from fastapi import FastAPI, UploadFile, HTTPException
from paddleocr import PaddleOCR

app = FastAPI(title="PaddleOCR Service")
ocr = PaddleOCR(use_angle_cls=True, lang="ch")

@app.get("/health")
def health():
    return {"status": "ok"}

@app.post("/ocr")
async def recognize(file: UploadFile):
    try:
        if file.content_type not in ("image/png", "image/jpeg"):
            raise HTTPException(400, "Unsupported file type")
        content = await file.read()
        result = ocr.ocr(content, cls=True)
        return {"text": [line[1][0] for block in result for line in block]}
    except Exception as e:
        raise HTTPException(500, str(e))
```'''
