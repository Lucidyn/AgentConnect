# Phase 3 — Negotiation Protocol & Distributed Workers

## 1. Negotiation protocol (v0.8) ✅

See runtime flow in `backend/core/negotiation.py`.

```bash
NEGOTIATION_MAX_ROUNDS=2
```

## 2. Distributed workers (v0.9) ✅

### Architecture

```
┌─────────────┐  XADD assignments   ┌──────────────────┐
│ API +       │ ──────────────────► │ Redis Stream     │
│ Planner     │                     │ ac:assignments   │
└──────┬──────┘                     └────────┬─────────┘
       │ XREADGROUP results                  │ XREADGROUP
       │                                     ▼
       │              ┌──────────────────────────────────┐
       │              │ Worker processes (one agent each)   │
       │              │  Research / Coder / Reviewer / ...  │
       │              └──────────────────┬───────────────┘
       │                                 │ XADD results
       ▼                                 ▼
┌──────────────────────────────────────────────────────────┐
│ Redis Stream ac:results → API injects Message → Planner   │
└──────────────────────────────────────────────────────────┘
```

### Components

| Module | Role |
|--------|------|
| `backend/core/worker_stream.py` | Redis / in-memory stream hub |
| `backend/core/worker_dispatcher.py` | Route assignments remote vs local |
| `backend/core/worker_runner.py` | Execute assignment on worker agent |
| `backend/worker/platform.py` | Worker process bootstrap |
| `backend/worker/run.py` | CLI entry |

### Enable distributed mode

**API / Planner process:**

```bash
DISTRIBUTED_WORKERS=true
USE_REDIS=true
WORKER_AGENTS=Research,Coder,Reviewer   # empty = all non-Planner agents
```

**Worker processes (one per agent):**

```bash
WORKER_MODE=true
WORKER_AGENT_NAME=Coder
USE_REDIS=true
REDIS_URL=redis://localhost:6379/0
python -m backend.worker.run
```

**Docker Compose (multi-container):**

```bash
docker compose up --build
# nginx → api + api-replica-2 + workers + postgres + redis
```

### Local dev without Redis

Tests use a shared in-memory stream (`USE_REDIS=false` + `DISTRIBUTED_WORKERS=true`) in a single pytest process.

### Envelope schemas

`backend/core/worker_protocol.py`:

- `WorkerTaskEnvelope` — Planner → worker
- `WorkerResultEnvelope` — worker → Planner

## 3. Horizontal API + shared Postgres (v1.0) ✅

### Architecture

```
                    ┌─────────────┐
   HTTP :8000 ─────►│ nginx LB    │
                    └──────┬──────┘
              ┌────────────┴────────────┐
              ▼                         ▼
       ┌─────────────┐           ┌─────────────┐
       │ API replica │           │ API replica │
       │  (Planner)  │           │  (Planner)  │
       └──────┬──────┘           └──────┬──────┘
              │                         │
              └────────────┬────────────┘
                           ▼
                  ┌─────────────────┐
                  │   PostgreSQL    │
                  │ tasks + outbox  │
                  └─────────────────┘
```

### Components

| Module | Role |
|--------|------|
| `backend/core/db/base.py` | SQLite / Postgres async adapters |
| `backend/core/db/schema.py` | Shared DDL + migrations |
| `backend/core/replica.py` | `API_REPLICA_ID` identity |
| `backend/core/task_store.py` | `dequeue` (`SKIP LOCKED`), `claim_for_planning` |

### Enable multi-replica mode

```bash
DATABASE_URL=postgresql://agent:agent@localhost:5432/agentconnect
API_REPLICA_ID=api-1          # unique per replica
USE_REDIS=true                  # shared message bus
DISTRIBUTED_WORKERS=true        # optional remote agents
```

- **Queue**: `dequeue()` uses `FOR UPDATE SKIP LOCKED` on Postgres so only one replica claims each queued task.
- **Planner**: `claim_for_planning()` prevents duplicate plan generation when Redis delivers the same User message to multiple replicas.
- **Outbox**: message reliability uses the same Postgres database as tasks.

### Rollout status

| Step | Status |
|------|--------|
| 3a Negotiation in-process | ✅ |
| 3b Worker CLI scaffold | ✅ |
| 3c Planner publishes to stream | ✅ |
| 3d Workers execute + publish results | ✅ |
| 3e Horizontal API + shared Postgres | ✅ |

### Environment

```bash
DATABASE_URL=
DATABASE_POOL_SIZE=10
API_REPLICA_ID=
DISTRIBUTED_WORKERS=false
WORKER_MODE=false
WORKER_AGENT_NAME=
WORKER_AGENTS=
WORKER_STREAM_KEY=ac:assignments
WORKER_RESULT_STREAM_KEY=ac:results
WORKER_CONSUMER_GROUP=ac-workers
WORKER_POLL_INTERVAL=2
```

### Postgres integration tests (local only)

`tests/` is not tracked in Git. Run locally when Postgres is available:

```bash
DATABASE_URL=postgresql://agent:agent@localhost:5432/agentconnect pytest -m postgres
```
