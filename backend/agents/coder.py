"""Coder Agent — reads shared memory for cross-agent context."""

from __future__ import annotations

from backend.constants import PLANNER
from backend.core.agent import Agent
from backend.models.message import Message, MessageType

SYSTEM_PROMPT = """你是 Coder Agent，负责根据需求和调研结果编写代码。
输出应包含：实现思路、核心代码（Python）、依赖说明、运行方式。"""


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
        result = await self.llm.chat(
            SYSTEM_PROMPT,
            f"背景：\n{context}\n\n编码任务：{task}" if context else f"编码任务：{task}",
            fallback,
        )

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

    def _mock_code(self, task: str) -> str:
        task_lower = task.lower()
        if "ocr" in task_lower or "paddle" in task_lower:
            return self._fixed_code()
        if "yolo" in task_lower:
            return (
                "```python\nfrom fastapi import FastAPI, UploadFile\n"
                "from ultralytics import YOLO\n\n"
                'app = FastAPI()\nmodel = YOLO("yolov11n.pt")\n\n'
                "@app.post('/detect')\nasync def detect(file: UploadFile):\n"
                "    return {'detections': model(await file.read())[0].tojson()}\n```"
            )
        return (
            f"```python\n# {task[:60]}\nfrom fastapi import FastAPI\n\n"
            "app = FastAPI()\n\n"
            "@app.get('/health')\ndef health():\n"
            "    try:\n"
            "        return {'status': 'ok'}\n"
            "    except Exception as e:\n"
            "        return {'status': 'error', 'detail': str(e)}\n```"
        )

    def _fixed_code(self) -> str:
        return '''```python
from fastapi import FastAPI, UploadFile, HTTPException
from paddleocr import PaddleOCR

app = FastAPI(title="PaddleOCR Service")
ocr = PaddleOCR(use_angle_cls=True, lang="ch")

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
