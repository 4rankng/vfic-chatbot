# Performance Baseline

> Performance requirements and constraints for the ChatBot (VFIC miniCRM) platform.
> Production runs on a **2 vCPU DigitalOcean droplet** — all decisions must account for this constraint.
> Also see [`../docs/HLD.md`](../docs/HLD.md) for the deployment latency strategy.

## Production Constraint

- **2 vCPU DigitalOcean droplet** at `bot.tingting.vip`.
- 10-service Docker Compose stack: postgres, redis, web, worker-chatbot, worker-ingest, worker-followup, scheduler, frontend, adminer, caddy.
- Every architectural decision must be evaluated against this constraint. See [`docs/HLD.md`](../docs/HLD.md) "Deployment and latency on your current droplet" for keep/change/defer analysis.

## Bot Reply Latency Budget

**Measured prod baseline (2026-09-26, 284 turns / 24 h, `BotRun.stage_timings`):**

| Stage | p50 | p95 |
|---|---|---|
| webhook → worker pickup | 25 ms | 66 ms |
| preamble (worker setup) | 132 ms | — |
| **agent LLM generation** | **8,915 ms** | per-call p90 12,602 ms |
| Jev router fan-out | 914 ms | — |
| prefetch / retrieval | 113 ms | 1,784 ms |
| DB round trips | 202 ms | — |
| send to channel | 614 ms | — |
| **end-to-end** | **11,959 ms** | **20,178 ms** |

- **Target:** end-to-end under 5 s for the candidate; SLO `full_answer_ms = 4,000 ms`.
  Current p50 is ~2.4× the target — the gap is generation time, not queueing
  (`queue_depth` was 0 on every turn) and not CPU (`llm_queue_ms` p50 = 4 ms).
- **There is no zero-LLM fast lane.** Every inbound message reaches the model
  (`runner.py`: "Final replies do not use a template fast lane"), so greetings
  (`small_talk`, 22 turns/24 h) also cost ~8 s of generation.
- **Generation dominates because of decode throughput, not prompt size.**
  Time-to-first-token at a 15–16 k-token prompt is only 0.8–2.2 s; the remaining
  ~7–12 s is the model emitting ~400–700 tokens at the provider's rate.

**Token-plan model throughput (measured 2026-09-26 from the prod container, same
12 k-token prompt + tools + tool result):**

| Model | full turn p50 | reasoning tokens | notes |
|---|---|---|---|
| MiniMax-M2.7-highspeed (prod primary) | 8,130 ms | 77 | thinking cannot be disabled (5 param shapes tried) |
| MiniMax-M2.1-highspeed | 7,071 ms | 22 | |
| MiniMax-M3 | 11,768 ms | 41 | |
| **Xiaomi MiMo v2.6-flash, thinking off** | **5,227 ms** | **0** | `thinking:{type:disabled}` works |
| Xiaomi MiMo v2.6-pro, thinking off | 6,328 ms | 0 | |

- **`reasoning_mode` is now a first-class client input** (`graph/clients.py`
  `_resolve_reasoning_mode`, default `off`): MiMo gets a thinking-disable field,
  OpenRouter is no longer pinned to `effort: high`, and MiniMax deliberately gets
  no field (unsupported there). Read via `getattr`, so it is live before the
  settings field lands.
- **Output cap** (`_agent_max_tokens`, default unset): measured — a 400-token cap
  on the token plans still finished with `finish_reason=stop`, cutting a MiniMax
  turn from 8,489 ms to ~6,100 ms; 250 truncated mid-answer on MiniMax.
- **Progressive delivery is live** (`llm_progressive_send`, default on): the
  agent call streams, and the first complete, substance-gated, grounded bubble is
  sent while the rest of the answer is still generating; the remainder follows
  through the unchanged claim→dispatch path. Guard rails: the durable outbox
  dispatcher is required, a lost ownership claim sends nothing, grounding and the
  reasoning strip run per bubble, and the remainder is a true suffix of the raw
  stream (never sent twice). Any doubt falls back to the single-message path.
  One admin toggle disables it.
- **Verify the streaming path live before any deploy that touches the LLM path:**
  `backend/scripts/verify_streaming_turn.py` exercises the app's own client
  builder + agent loop against a real provider and fails on a broken stream, a
  dropped usage block, or streamed text that disagrees with the returned reply.
  `--sweep` compares the cheap/high-throughput candidates. Measured 2026-09-26
  from a developer machine:

  | model | deltas | ttft | first bubble | total | early gain |
  |---|---|---|---|---|---|
  | deepseek/deepseek-v4.1-flash | 66 | 900 ms | 1,748 ms | 2,452 ms | **705 ms** |
  | qwen/qwen3-30b-a3b-instruct-2507 | 207 | 407 ms | 746 ms | 1,321 ms | 576 ms |
  | google/gemini-2.5-flash-lite | 8 | 1,024 ms | 1,719 ms | 1,757 ms | ~0 |
  | openai/gpt-4o-mini | 109 | 1,969 ms | 2,739 ms | 2,829 ms | ~0 |
  | MiniMax-M2.7-highspeed | 20 | 2,007 ms | 10,769 ms | 10,796 ms | ~0 (bursty from this host) |

  **Early-delivery value is a property of the provider's delta cadence, not of
  average tok/s:** a burst-style stream (few large chunks) reaches the bubble
  threshold at almost the same moment it finishes, so progressive delivery buys
  nothing there. Always re-measure on the host and network that will serve the
  traffic before enabling it.
- **Proactive follow-up:** not latency-sensitive (runs in the `followup` queue,
  30-min tick).

## Database Pool Sizing

Configured in `backend/app/core/config.py`, applied in `backend/app/core/db.py`:

| Setting | Value | Purpose |
|---|---|---|
| `db_pool_size` | 10 | Base connections per async engine |
| `db_max_overflow` | 10 | Burst capacity (max 20 total) |
| `db_pool_timeout` | 30s | Wait for connection before failing |
| `db_pool_recycle` | 1800s (30 min) | Prevent stale connections |
| `pool_pre_ping` | True | Validate connection before use |

**Never increase pool size without verifying Postgres `max_connections` can handle it.** The droplet has limited memory.

## LLM Concurrency Control

- **Cross-process Redis semaphore** (`backend/app/graph/llm_semaphore.py`) limits concurrent LLM/embedding calls across web + all workers.
- Prevents overloading the 2 vCPU droplet with concurrent LLM requests.
- Configured via `LLM_CONCURRENCY_LIMIT` env var.

## RAG Retrieval

- **pgvector HNSW ANN** for approximate nearest neighbor search (`rag_ann_enabled`).
- **Exact re-rank** on top candidates for precision.
- **RRF fusion** (Reciprocal Rank Fusion) for hybrid lexical + vector search.
- **Semantic cache** (`semantic_cache.py`) for non-personalized knowledge queries — avoids redundant LLM calls.
- **Reranker** for multilingual (Vietnamese) result quality.

See [`docs/system-architecture.md`](../docs/system-architecture.md) §10 (RAG retrieval) for details.

## Queue Model (RQ)

Four queues isolate work by priority:

| Queue | Priority | Purpose |
|---|---|---|
| `webhook_high` | Highest | Chat turns (candidate waiting) |
| `recovery` | Low | Recovered turns from the reconcile sweep (never ahead of a live turn) |
| `persistence_low` | Low | Candidate extraction after SENT |
| `ingest` | Normal | Knowledge document/KB version pipeline |
| `followup` | Normal | Proactive follow-up + reconcile sweeps |

- **Reconcile worker** (`reconcile_worker.py`) runs every 60s — finds lost/stuck bot turns and re-enqueues. This is the reliability guarantee.
- **Proactive tick** runs every 1800s (30 min).

## Frontend Performance

### Virtualization
- **virtua** (`VList`) required for long lists: conversations, messages, bot runs.
- **Never render unbounded lists.** If a list can exceed 50 items, virtualize it.

### Bundle Chunking
Manual chunks in `vite.config.ts`:
- `react-vendor`, `ra-vendor`, `tanstack-vendor`, `lucide-vendor`, `router-vendor`, `realtime-vendor`, `forms-vendor`, `virtua-vendor`.

### Code Splitting
- Secondary routes lazy-loaded: `ProfilePage`, `ForgotPasswordPage` via `React.lazy()`.
- PWA enabled via `vite-plugin-pwa` (autoUpdate, workbox).

### Query Caching
- TanStack Query `staleTime: 30s`, `gcTime: 24h`, `networkMode: "offlineFirst"`.
- Realtime Socket.IO events trigger `invalidateQueries()` to bypass staleTime for fresh data.

### PWA
- `vite-plugin-pwa` with autoUpdate.
- `vite:preloadError` handler in `main.tsx` reloads on chunk load failure after deploy (with `sessionStorage` guard against infinite loops).

## Performance Checklist (Before Declaring Done)

- [ ] No N+1 queries (use `selectinload` / `joinedload` for relations)
- [ ] No blocking I/O on the async event loop (crypto on `asyncio.to_thread`)
- [ ] Long lists virtualized with `virtua` (`VList`)
- [ ] No unbounded loops or recursive calls without depth limits
- [ ] LLM calls respect the concurrency semaphore
- [ ] DB queries use appropriate indexes (check `EXPLAIN ANALYZE` for new queries)
- [ ] Frontend bundle size hasn't regressed (run `npm run build:analyze` if unsure)
