# Performance Baseline

> Performance requirements and constraints for the ChatBot (VFIC miniCRM) platform.
> Production runs on a **2 vCPU DigitalOcean droplet** — all decisions must account for this constraint.
> Also see [`../docs/HLD.md`](../docs/HLD.md) for the deployment latency strategy.

## Production Constraint

- **2 vCPU DigitalOcean droplet** at `bot.tingting.vip`.
- 10-service Docker Compose stack: postgres, redis, web, worker-chatbot, worker-ingest, worker-followup, scheduler, frontend, adminer, caddy.
- Every architectural decision must be evaluated against this constraint. See [`docs/HLD.md`](../docs/HLD.md) "Deployment and latency on your current droplet" for keep/change/defer analysis.

## Bot Reply Latency Budget

- **Fast lane (greetings, thanks, goodbye, help):** zero-LLM, template responses — sub-100ms.
- **FAQ bypass:** deterministic short-circuit, no LLM — sub-200ms.
- **Agent turn (full LLM):** within LLM latency budget (MiniMax/OpenRouter typical: 1–3s). Target end-to-end under 5s for the candidate.
- **Proactive follow-up:** not latency-sensitive (runs in `followup` queue, 30-min tick).

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
- **react-virtuoso** required for long lists: conversations, messages, bot runs.
- **Never render unbounded lists.** If a list can exceed 50 items, virtualize it.

### Bundle Chunking
Manual chunks in `vite.config.ts`:
- `react-vendor`, `ra-vendor`, `tanstack-vendor`, `lucide-vendor`, `router-vendor`, `realtime-vendor`, `forms-vendor`, `virtuoso-vendor`.

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
- [ ] Long lists virtualized with `react-virtuoso`
- [ ] No unbounded loops or recursive calls without depth limits
- [ ] LLM calls respect the concurrency semaphore
- [ ] DB queries use appropriate indexes (check `EXPLAIN ANALYZE` for new queries)
- [ ] Frontend bundle size hasn't regressed (run `npm run build:analyze` if unsure)
