# Phase 3 — Negotiation Protocol & Distributed Workers

## 1. Negotiation protocol (v0.8)

### Message intents

| Intent | Direction | Purpose |
|--------|-----------|---------|
| `negotiation_question` | Planner → Agent | Ask upstream to clarify an open question |
| `negotiation_decision` | Planner → Agent | Record agreed answer on blackboard |
| `agent_query` / `agent_answer` | Agent ↔ Agent | Ad-hoc bounded queries (existing) |

### Runtime flow (single-node)

1. Agent completes assignment → facts posted to blackboard.
2. Output lines ending with `?` become `open_questions`.
3. If `negotiation=true` and `collaboration_mode=blackboard`:
   - `run_negotiation_round()` resolves one question per step using upstream `ctx.results`.
   - Answer posted as `decision` on blackboard; question marked `[resolved]`.
   - `negotiation_state.round` increments until `NEGOTIATION_MAX_ROUNDS`.
4. Next assignment dispatch includes blackboard + unresolved questions.

### Configuration

```bash
NEGOTIATION_MAX_ROUNDS=2
```

## 2. Distributed workers (design)

### Current constraint

- All agents run **in-process** inside `Platform.start()`.
- Redis is used for pub/sub only, not assignment distribution.
- `MAX_CONCURRENT_TASKS` is enforced in a single API process.

### Target architecture

```
┌─────────────┐     enqueue      ┌──────────────────┐
│  API /      │ ───────────────► │ Redis Stream     │
│  Planner    │                  │ ac:assignments   │
└─────────────┘                  └────────┬─────────┘
                                          │ XREADGROUP
                    ┌─────────────────────┼─────────────────────┐
                    ▼                     ▼                     ▼
              ┌──────────┐         ┌──────────┐         ┌──────────┐
              │ Worker   │         │ Worker   │         │ Worker   │
              │ Research │         │ Coder    │         │ Writer   │
              └────┬─────┘         └────┬─────┘         └────┬─────┘
                   │                    │                    │
                   └────────────────────┼────────────────────┘
                                        ▼
                              ┌──────────────────┐
                              │ Redis Stream     │
                              │ ac:results       │
                              └────────┬─────────┘
                                       ▼
                              ┌──────────────────┐
                              │ Planner /        │
                              │ PlanOrchestrator │
                              └──────────────────┘
```

### Envelope schemas

See `backend/core/worker_protocol.py`:

- `WorkerTaskEnvelope` — assignment dispatched to worker
- `WorkerResultEnvelope` — result returned to orchestrator

### Rollout steps

1. **3a** — Negotiation protocol in-process (done in v0.8).
2. **3b** — `WORKER_MODE=true` stub process (`python -m backend.worker.run`).
3. **3c** — Planner publishes `WorkerTaskEnvelope` to Redis Stream instead of in-process `send()`.
4. **3d** — Worker processes load agent plugins; publish `WorkerResultEnvelope`.
5. **3e** — Horizontal API replicas + shared SQLite/Postgres task store.

### Environment

```bash
WORKER_MODE=false          # true = run standalone worker loop
WORKER_STREAM_KEY=ac:assignments
WORKER_RESULT_STREAM_KEY=ac:results
WORKER_POLL_INTERVAL=2
```
