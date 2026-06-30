# Agent Connect

**Multi-Agent Collaboration Platform** — 多智能体协作平台

一个可演示、可扩展的多 Agent 通信与协作系统。Agent 通过 Message Bus 异步通信，像邮箱一样拥有 Inbox / Outbox / Memory。

```
                User
                  │
            Planner Agent
          /        │        \
         /         │         \
 Research     Coding      Vision
   Agent        Agent       Agent
       \          │         /
        \         │        /
         Reviewer Agent
                │
           Final Result
```

## 快速开始

```bash
cd agent_connect
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # 可选：LLM / API_KEY
python -m backend.run
```

打开 http://localhost:8000

Docker：`docker compose up --build`

## 配置

```bash
# LLM — openai | openai_compatible | anthropic
LLM_PROVIDER=openai
OPENAI_API_KEY=sk-...
ANTHROPIC_API_KEY=sk-ant-...   # LLM_PROVIDER=anthropic 时

# 插件过滤（空 = manifest 中全部 enabled）
ENABLED_AGENTS=
ENABLED_TOOLS=

# 可选 API 鉴权（保护 POST /tasks、取消、死信重投）
API_KEY=

# 任务队列 & 消息可靠性
MAX_CONCURRENT_TASKS=3
MESSAGE_RELIABILITY=true
CLEAR_FAILED_OUTBOX=false   # true = 启动时清空 failed outbox
```

不配置 API Key 时，Agent 使用内置规则模式，可完整演示通信流程。

## 插件接入

编辑 `plugins/manifest.yaml`，无需改平台代码：

```yaml
agents:
  - name: vision
    module: plugins.vision.agent
    class: VisionAgent
    runtime: native              # 默认，自研 Agent 循环
    enabled: true
  - name: summarizer
    module: plugins.openai_agents.summarizer
    class: SummarizerAgent
    runtime: openai_agents       # OpenAI Agents SDK
    enabled: false
  - name: router
    module: plugins.langgraph.router
    class: RouterAgent
    runtime: langgraph           # LangGraph 状态图
    enabled: false
```

| runtime | 基类 | 依赖 |
|---------|------|------|
| `native` | `Agent` | 无 |
| `openai_agents` | `OpenAIAgentsBridge` | `pip install openai-agents` |
| `langgraph` | `LangGraphBridge` | `pip install langgraph` |

未安装 SDK 时 Bridge 自动降级为规则 fallback，不影响平台启动。

参考示例：`plugins/vision/`、`plugins/openai_agents/`、`plugins/langgraph/`

## API

| 端点 | 说明 |
|------|------|
| `POST /tasks` | 提交任务（支持 `Idempotency-Key` header） |
| `GET /tasks/{id}` | 任务详情 |
| `GET /tasks/{id}/timeline` | 任务时间线 |
| `GET /tasks/{id}/stream` | SSE 任务状态流 |
| `POST /tasks/{id}/approve` | 人工审批（approve / retry / reject） |
| `GET /metrics` | Prometheus 指标 |
| `GET /traces/{trace_id}` | 按 trace 查消息链路 |
| `GET /messages/dead-letter` | 死信列表 |
| `DELETE /messages/dead-letter` | 清空死信（需 API_KEY） |
| `POST /messages/dead-letter/{id}/retry` | 重投死信 |
| `GET /agents/discover?q=` | Agent 发现 |
| `GET /runtimes` | 可用 Runtime 列表 |
| `GET /health` | 健康检查（含 llm_provider、agent_runtimes） |
| `/ws/messages` | WebSocket 实时消息 |

```bash
curl -X POST http://localhost:8000/tasks \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: my-task-001" \
  -d '{"task": "写一个 PaddleOCR 服务"}'
```

## 项目结构

```
agent_connect/
├── backend/
│   ├── api/              # HTTP 路由与 schemas
│   ├── agents/           # 内置 Agent
│   ├── core/             # Agent、Bus、Registry、LLM、Runtime
│   ├── plugins/loader.py # manifest 动态加载
│   ├── constants.py      # 共享常量
│   └── app.py            # FastAPI 入口（薄层）
├── plugins/
│   ├── manifest.yaml     # 插件清单
│   └── vision/           # 示例外挂 Agent
└── tests/
```

## 演进路线

| 阶段 | 内容 | 状态 |
|------|------|------|
| Phase 1 | 通信层：Message Bus + Agent 基类 + Registry | ✅ |
| Phase 1.5–1.8 | 共享记忆、动态调度、任务队列、Outbox、Trace | ✅ |
| **v0.6** | 多 Provider LLM、YAML 插件、Runtime 适配、SSE/Trace | ✅ 当前 |
| Phase 2 | 并行调度、Human-in-the-loop、Prometheus | ✅ 当前 |
| Phase 3 | 自治协商 + 分布式部署 | 待开发 |

### v0.7 新增

- **Planner 并行**：`assignment_id` 精确匹配；Research + Vision 可并行
- **Human-in-the-loop**：审查失败 → `waiting_approval` → `POST /tasks/{id}/approve`
- **Prometheus**：`GET /metrics`（队列、Outbox、LLM、Agent 耗时）
- **前端**：任务时间线 + 审批按钮

### v0.6 新增

- **LLM Provider**：OpenAI / Anthropic / OpenAI 兼容 API
- **插件 manifest**：`module` + `class` 动态加载，支持 per-agent 配置
- **Runtime 适配**：`native` / `openai_agents` / `langgraph`，manifest 按 Agent 指定
- **Bridge 基类**：`OpenAIAgentsBridge`、`LangGraphBridge` + 示例插件
- **NativeRuntime**：统一 Agent 挂载/卸载
- **任务**：幂等提交、取消、SSE 状态流、Timeline API
- **可观测性**：`/traces/{id}`、死信查询与重投
- **消息去重**：Agent 按 `message.id` 幂等；带 `task_id` 时写入 task context 持久化
- **可选 API Key** 鉴权

## 技术栈

- **LLM**: OpenAI / Anthropic（可选，规则 fallback）
- **通信**: Redis Pub/Sub / In-Memory + SQLite Outbox
- **API**: FastAPI + WebSocket + SSE
- **存储**: SQLite（Registry / Tasks / Outbox）、Qdrant（共享记忆）
- **部署**: Docker Compose

## 测试

```bash
pytest tests/ -q                    # 默认（无 Redis 时跳过 redis 标记用例）
pytest tests/ -q -m redis           # 仅 Redis 集成测试（需本地 Redis）
```

GitHub Actions CI：每次 push/PR 跑全量 pytest + Docker build。

覆盖：任务队列、Plan 持久化、Outbox 清理、消息去重持久化、Bus、端到端流水线、插件、Runtime、指标等。
