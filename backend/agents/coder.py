"""Coder Agent — reads shared memory for cross-agent context."""

from __future__ import annotations

import re

from backend.constants import PLANNER
from backend.core.agent import Agent
from backend.core.project_workspace import (
    apply_file_blocks,
    build_tree_summary,
    resolve_workspace_path,
)
from backend.core.query_extract import yolo_model_name
from backend.models.message import Message, MessageType

SYSTEM_PROMPT = """你是 Coder Agent。只输出：
1. 核心 Python 代码块（FastAPI 服务必须包含 GET /health 健康检查端点）
2. 一行运行方式
不要长篇解释。
若用户指定 YOLO 版本（如 YOLO26），模型权重须对应该版本（如 yolo26n.pt），不得改用 YOLOv6 或其他版本。"""

WORKSPACE_SYSTEM_PROMPT = """你是 Coder Agent，在已有本地项目目录中工作。
输出格式要求：
1. 每个文件单独一个代码块，第一行标注相对路径，例如：
```python src/main.py
...代码...
```
2. 可新建或修改文件；路径相对于项目根目录
3. FastAPI 服务必须包含 GET /health
4. 最后一行给出运行/测试命令
不要长篇解释。"""

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
        ctx = await self.load_task_context()
        workspace_root = None
        if ctx.workspace_path:
            try:
                workspace_root = resolve_workspace_path(ctx.workspace_path)
            except ValueError:
                workspace_root = None

        if "调研结果" in task:
            self.remember("research_context", task)

        shared = await self.recall_shared(task)
        research = self.recall("research_context", "")
        if not research and "调研结果" not in task and not workspace_root:
            try:
                answer = await self.ask_agent_and_wait(
                    "Research",
                    f"请简要调研与以下编码任务相关的 API/库/最佳实践：\n{task[:500]}",
                )
                if answer:
                    research = answer
                    self.remember("research_context", research)
            except ValueError:
                pass
        context_parts = [p for p in (research, shared) if p]
        context = "\n\n".join(context_parts)

        if workspace_root:
            tree = build_tree_summary(workspace_root)
            system = WORKSPACE_SYSTEM_PROMPT
            user_parts = [tree, f"编码任务：{task}"]
            if context:
                user_parts.insert(1, f"背景：\n{context}")
            prompt = "\n\n".join(user_parts)
        else:
            system = SYSTEM_PROMPT
            prompt = f"背景：\n{context}\n\n编码任务：{task}" if context else f"编码任务：{task}"

        fallback = self._mock_code(task)
        result = await self.llm_chat(
            system,
            prompt,
            fallback,
            role=self.role,
            stream=True,
            message=message,
        )
        if not workspace_root:
            result = self._ensure_health_endpoint(result)

        write_note = ""
        if workspace_root and ctx.workspace_write_enabled:
            applied = apply_file_blocks(workspace_root, result)
            if applied.written:
                write_note = "\n\n【已写入工作区】\n" + "\n".join(f"- {p}" for p in applied.written)
                result += write_note

                def _record(ctx_obj):
                    ctx_obj.workspace_files_written.extend(applied.written)

                if self.task_store and self._current_task_id:
                    await self.task_store.mutate_context(self._current_task_id, _record)
            elif applied.skipped:
                result += "\n\n【写入跳过】\n" + "\n".join(applied.skipped)

        await self.store_in_shared_memory(
            content=result,
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
