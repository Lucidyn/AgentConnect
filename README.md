# Agent Connect

**Multi-Agent Collaboration Platform** — 多智能体协作平台 v1.0

可演示、可扩展的单节点多 Agent 编排系统。Agent 通过 Message Bus 异步通信；支持 DAG 计划、模板流水线与可视化编排。

**三步使用**：选模板（可选）→ 输入任务 → 提交。

```
                    User
                      │
                Planner Agent
                      │
        ┌─────────────┼─────────────┐
        ▼             ▼             ▼
   Research       Analyst        Coder
        │             │             │
        └──────┬──────┴──────┬──────┘
               ▼             ▼
            Writer      TestRunner
               │             │
               └──────┬──────┘
                      ▼
                 Reviewer / Translator
                      │
                Final Result
```

> **部署模型**：默认单进程 + SQLite。`DISTRIBUTED_WORKERS=true` 时 Worker 独立进程（Redis Stream）。`DATABASE_URL` 启用 Postgres 后，可运行多个 API 副本（nginx 负载均衡）。见 [`docs/phase3-architecture.md`](docs/phase3-architecture.md)。

## 快速开始

```bash
cd agent_connect
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
pip install -r requirements-dev.txt   # 测试 / coverage
cp .env.example .env
python -m backend.run
```

打开 http://localhost:8000 — **运行** 页提交任务，**编排 (DAG)** 页可视化编辑计划。

Docker：

```bash
docker compose up --build
# nginx :8000 → api + replicas + workers + postgres + redis
# Prometheus :9090 · Grafana :3000 (admin/admin)
```

前端模块化构建（可选）：

```bash
cd frontend && npm install --cache ./.npm-cache && npm run build
```

## 内置 Agent

| Agent | 职责 |
|-------|------|
| Planner | 拆解任务、调度 DAG |
| Research | 调研、工具调用（arXiv/GitHub） |
| Coder | 代码实现 |
| Writer | 写作 / 文案 |
| Analyst | 分析 / 报告 |
| Translator | 翻译 |
| TestRunner | 轻量测试 |
| Reviewer | 质量审查 |

插件：`plugins/manifest.yaml`（Vision 默认启用；Router/Summarizer 可选 runtime 插件）。

## 编排能力

### 1. 自动计划（Planner LLM）

不指定模板时，由 Planner 根据任务动态生成 DAG（支持并行分支）。

### 2. 固定模板

`plugins/plan_templates.yaml`：

| ID | 流水线 |
|----|--------|
| `research_write_translate` | 调研 → 写作 → 翻译 → 审查 |
| `hybrid_report` | Research → Analyst → Writer → Reviewer |
| `parallel_research` | Research ∥ Analyst → Writer → Reviewer |
| `coding_standard` | Research → Coder → TestRunner → Reviewer |

```bash
curl -X POST http://localhost:8000/tasks \
  -H "Content-Type: application/json" \
  -d '{"task":"行业分析","template_id":"hybrid_report"}'
```

### 3. 可视化 DAG 编排

前端 **编排 (DAG)** 页：拖拽节点、端口连线、校验后提交；可保存/载入自定义模板。

### 4. 运维能力

- Token 用量：`GET /tasks/{id}/usage`
- 任务续跑：`POST /tasks/{id}/resume`（可选 `from_assignment`）
- 时间线耗时：`GET /tasks/{id}/timeline`（含 `duration_ms`）

## 分布式部署

```bash
docker compose up --build
# nginx :8000 → api + api-replica-2，postgres 共享任务库，worker-research/coder/reviewer
```

单 Worker 本地调试（需自行启动 Redis）：

```bash
# 终端 1 — API
DISTRIBUTED_WORKERS=true USE_REDIS=true python -m backend.run

# 终端 2 — Coder worker
WORKER_MODE=true WORKER_AGENT_NAME=Coder USE_REDIS=true python -m backend.worker.run
```

## 配置

```bash
# LLM
LLM_PROVIDER=openai          # openai | openai_compatible | anthropic
OPENAI_API_KEY=
LLM_TIMEOUT_SECONDS=120

# 鉴权 — 设置后任务/Agent/工具/指标等 API 需 X-API-Key（/health 保持公开）
API_KEY=

# 任务队列
MAX_CONCURRENT_TASKS=3
MESSAGE_RELIABILITY=true

# Fast mode（少调 LLM、短上下文）
FAST_MODE=false
FAST_SKIP_PLANNER_LLM=false
ASSIGNMENT_CONTEXT_MAX_CHARS=4000
LLM_STREAMING=true

# HTTP 工具插件（MCP 风格）
HTTP_TOOL_BASE_URL=

# OpenTelemetry（可选，见 requirements-optional.txt）
# OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318/v1/traces

# 协商（高级，默认关闭）
NEGOTIATION_MAX_ROUNDS=2

# Phase 3 — 分布式 Worker + 水平扩展
DISTRIBUTED_WORKERS=false
DATABASE_URL=              # postgresql://... 启用共享 Postgres（多副本）
API_REPLICA_ID=              # 每个 API 实例唯一 ID
WORKER_MODE=false
```

完整变量见 [`.env.example`](.env.example)。

## API

| 端点 | 说明 |
|------|------|
| `POST /tasks` | 提交任务（`template_id` / `custom_plan`） |
| `GET /tasks` | 任务列表 |
| `GET /tasks/{id}` | 任务详情 |
| `GET /tasks/{id}/usage` | LLM Token 用量与估算成本 |
| `GET /tasks/{id}/workspace` | 计划快照与分步产出 |
| `GET /tasks/{id}/timeline` | 时间线（含耗时） |
| `GET /tasks/{id}/stream` | SSE 状态流 |
| `GET /tasks/{id}/messages` | 任务消息 |
| `GET /tasks/{id}/artifacts` | 产物 |
| `GET /tasks/{id}/artifacts/{artifact_id}/download` | 下载产物 |
| `POST /tasks/{id}/resume` | 续跑失败/中断任务 |
| `POST /tasks/{id}/approve` | 人工审批 `approve` / `retry` / `reject` |
| `POST /tasks/{id}/cancel` | 取消任务 |
| `GET /templates` | 计划模板列表（内置 + 已保存） |
| `GET /templates/{id}` | 模板详情 |
| `POST /templates/saved` | 保存用户模板 |
| `DELETE /templates/saved/{id}` | 删除用户模板 |
| `POST /templates/validate` | 校验自定义 DAG |
| `POST /templates/preview` | 预览 DAG JSON |
| `GET /agents` | Agent 列表 |
| `GET /agents/discover?q=` | Agent 发现 |
| `GET /tools` | MCP 工具列表 |
| `GET /plugins/validate` | 校验 `manifest.yaml` 插件条目 |
| `GET /metrics` | Prometheus |
| `GET /traces/{trace_id}` | Trace 链路 |
| `GET /health` | 健康检查 |
| `/docs` | OpenAPI 文档 |
| `/ws/messages` | WebSocket 实时消息（`?api_key=` 或 header） |

```bash
curl -X POST http://localhost:8000/tasks \
  -H "Content-Type: application/json" \
  -H "X-API-Key: your-key" \
  -H "Idempotency-Key: task-001" \
  -d '{"task":"写一个 API"}'
```

错误语义：404/409/422 使用标准 HTTP 状态码；鉴权失败 401。

## 项目结构

```
agent_connect/
├── backend/
│   ├── api/              # HTTP 路由
│   ├── agents/           # 内置 Agent（8 个）
│   ├── core/             # Bus、编排、LLM、DB、Worker
│   ├── worker/           # 分布式 Worker 进程入口
│   └── static/           # Web UI + compose.js
├── frontend/           # Vite 模块化 UI 源码 → backend/static/assets/
├── deploy/               # nginx + Prometheus + Grafana 配置
├── plugins/
│   ├── manifest.yaml
│   └── plan_templates.yaml
├── docs/
│   └── phase3-architecture.md
└── tests/              # 单元与集成测试（CI 默认跑非 integration 子集）
```

## 演进路线

| 阶段 | 内容 | 状态 |
|------|------|------|
| Phase 1 | Message Bus + Agent + Registry | ✅ |
| Phase 2 | DAG 并行、审批、Prometheus、Outbox | ✅ |
| **v0.8** | 模板、DAG 编排 UI、黑板、协商协议、API 加固 | ✅ |
| **v0.9** | Phase 3 分布式 Worker（Redis Stream） | ✅ |
| **v1.0** | 多 API 副本 + Postgres 共享任务库 | ✅ 当前 |

### v1.0 新增（Phase 3e）

- **Postgres 任务库**：`DATABASE_URL=postgresql://...` 替代 SQLite（任务、消息、outbox 同库）
- **水平扩展**：`API_REPLICA_ID` + `claim_for_planning` / `dequeue SKIP LOCKED` 防重复调度
- **Docker Compose**：`postgres` + `api` + `api-replica-2` + `nginx` 负载均衡

### v0.9 新增

- **分布式 Worker**：`DISTRIBUTED_WORKERS` + Redis Stream 任务分发
- **Worker 进程**：`python -m backend.worker.run`（`WORKER_AGENT_NAME` 指定 Agent）
- **结果回传**：Worker → `ac:results` → API 注入 Planner
- **Docker Compose**：`worker-research` / `worker-coder` / `worker-reviewer` / `worker-writer` / `worker-analyst` / `worker-translator` / `worker-test_runner` 服务
- **健康检查**：`/health` 返回 `distributed_workers` 与 `remote_agents`

### v0.8 新增

- 计划模板 + 自定义 DAG + 可视化编排器
- Writer / Analyst / Translator 多领域 Agent
- 黑板协作与协商轮次（`NEGOTIATION_MAX_ROUNDS`）
- API 输入校验、`X-API-Key` 全路由保护（配置后）
- 前端 API Key、错误 Toast
- SQLite WAL、LLM 超时、Docker 数据卷
- CI import smoke + Docker smoke test

## 技术栈

- **LLM**: OpenAI / Anthropic / 兼容 API（规则 fallback）
- **通信**: Redis Pub/Sub 或 In-Memory + SQLite/Postgres Outbox
- **API**: FastAPI + WebSocket + SSE
- **存储**: SQLite（本地）或 Postgres（多副本）；Qdrant（共享记忆，可选；多进程请设 `USE_QDRANT=false` 或独立 Qdrant 服务）
- **部署**: Docker Compose（Postgres + nginx + workers）

## 测试

```bash
pip install -r requirements-dev.txt
pytest tests/ -q --ignore=tests/integration
pytest tests/ -q --cov=backend --cov-report=term-missing
pytest tests/ -q -m redis       # 需本地 Redis
pytest tests/ -q -m postgres    # 需 DATABASE_URL 指向 Postgres
```

GitHub Actions：import smoke + pytest（默认跳过 `tests/integration`）+ Docker build/health smoke。

## 插件接入

编辑 `plugins/manifest.yaml`：

```yaml
agents:
  - name: translator
    module: backend.agents.translator
    class: TranslatorAgent
    enabled: true
```

| runtime | 说明 |
|---------|------|
| `native` | 自研 Agent 循环 |
| `openai_agents` | OpenAI Agents SDK Bridge |
| `langgraph` | LangGraph Bridge |

**安全提示**：插件通过 `importlib` 加载，仅启用可信 manifest 条目。
