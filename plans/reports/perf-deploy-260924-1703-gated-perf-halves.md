# Gated perf halves — PERF-02 (deploy), PERF-07, PERF-12, PERF-08 (migration)

2026-09-24 · perf-deploy · uncommitted shared tree on `main`

All four user-approved gate-crossing halves are implemented and verified against the full unit lane. Nothing is deployed; every change takes effect on the next `make deploy` (blue/green) only.

## PERF-02 — Redis eviction policy + cachever flush-on-miss (deploy half)

`backend/docker-compose.yml` redis service now runs `--maxmemory-policy volatile-lru` instead of `allkeys-lru`, with a comment explaining the contract: only TTL'd keys (the embedding/RAG caches) are evictable, while the LLM semaphore token lists and `cachever:*` counters — which carry no TTL — can no longer be evicted under memory pressure. That removes the outage class outright (an evicted `llm_sem_tokens` suppressing every turn until every process restarts). The token-persistence half in `llm_semaphore.py` and the packed-embedding half in `graph/tools/_shared.py` belong to other teammates and were not touched.

`backend/app/core/cache.py` closes the resurrection hole the ticket describes. Previously `cache_version()` returned `"1"` for a missing counter, so a lost `cachever:knowledge` silently reset the namespace and made still-live stale `v{n}` entries readable again. Now a miss is treated as a full flush: the function seeds the counter at a fresh generation — `str(int(time.time()))` — via `SET NX` and returns it. Epoch scale is deliberately far above any INCR counter a namespace can ever carry, so the seeded generation cannot equal any version that existing cache entries were written under; every historical entry in the namespace becomes unreachable at once and ages out via TTL. `bump_cache_version()` got the same seed value for its `SET NX` recreate path (it previously recreated at `"2"`), because a bump that lands on an absent counter is the same miss and previously reintroduced the same stale-`v2` resurrection. Present counters keep pure Redis INCR semantics, untouched.

Why this is safe: every consumer uses the version as an opaque string inside cache keys, so the only observable effects are (a) a lost counter now invalidates instead of resurrecting, and (b) after this deploy the first read of each never-bumped namespace seeds a fresh generation, so namespaces that had been sitting on the logical default `v1` take a one-time cold refill bounded by their TTL. The error path (Redis unreachable) also returns a fresh unpersisted generation rather than `"1"` — nothing can be served through it because the cache reads/writes that would use the value fail too.

## PERF-07 — per-service DB pool budget and fast-fail timeout

`backend/docker-compose.yml` now pins the async pool per service via explicit `environment:` entries (which override `.env`, verified in the rendered config): web-blue and web-green get `DB_POOL_SIZE=8` / `DB_MAX_OVERFLOW=4`, and each worker (chatbot, persistence, ingest, followup, and the new maintenance) gets `4`/`2`. Worst case at steady state is 2×12 + 7×6 = 66 connections against the Postgres `max_connections=150` ceiling (~44%), leaving headroom for adminer, psql, and the one-shot backfill profile — down from the previous uniform 10+10 whose worst case (8×20 = 160) sat above the ceiling. Workers run one job at a time (`SimpleWorker`), so 4+2 remains ample per the ticket.

`backend/app/core/config.py`: `db_pool_timeout` default drops from 30 to 5 seconds, so a saturated pool fails fast into the recovery path instead of silently holding the per-chat lock (`bot_lock_ttl_seconds=180`) three times past the responsiveness SLA. The stale sizing comment above those fields was rewritten for the real topology (web-blue + web-green one uvicorn each, chatbot ×3, persistence, ingest, followup, maintenance — 9 resident DB-touching processes) with the 66-of-150 math inline so the next sizing decision isn't made against the phantom "6 chatbot replicas / ~13 processes" topology.

## PERF-12 — `maintenance` queue split + depth bounds

`backend/app/main.py` lifespan now constructs a second rq-scheduler bound to `queue_name="maintenance"` and registers `run_reconcile_tick` and `run_outbound_dispatch_tick` through it; `run_proactive_followup_tick` (and the retention / external-sync ticks, which were outside the approved move) stay on `followup`. Because rq-scheduler stores scheduled jobs in one connection-wide sorted set and `register_unique_tick` cancels by function name before re-registering with a stable id, the first boot of the new code automatically cancels the old followup-bound schedules — no manual Redis cleanup.

`backend/docker-compose.yml` gains a single-replica `worker-maintenance` service (`rq worker maintenance --url ${REDIS_URL}`, same image/healthcheck pattern as `worker-followup`, 4/2 pool env, 180s stop grace so a mid-sweep reconcile can finish on SIGTERM), and `worker-followup` stays as the proactive-nudge consumer with its comment updated to the narrowed role. Queue plumbing follows the existing patterns exactly: `run_worker.py` takes positional queue names (used by chatbot/persistence), while followup/ingest/maintenance use the bare `rq worker <queue>` CLI — verified against `run_worker.py`'s `sys.argv[1:]` handling and the compose `command:` lines. `worker-chatbot` replicas were deliberately not touched (the raise-to-4 option is gated on PERF-01/03/06 landing first).

Backpressure: `backend/app/workers/utils.py` now resolves a default `max_depth` from settings for `followup` and `maintenance` when a call site passes none — `followup_queue_max_depth=50` and `maintenance_queue_max_depth=20` in config, `0` disables, explicit `max_depth` at a call site always wins, and `webhook_high` is untouched (its call sites already pass `chat_queue_max_depth`, the reference pattern). This bounds the enqueue sites I don't own — the per-lead nudge fan-out in `followup_worker.enqueue_followup` and the ops manual trigger in `reconcile_worker.enqueue_reconcile_tick_now` — without editing those files. One honest limitation: scheduler-enqueued ticks bypass `enqueue_job` entirely, so the bounds guard the fan-out/manual paths, not rqscheduler's own enqueues.

## PERF-08 — `match_memories` halfvec cast (migration half)

`backend/alembic/versions/0001_baseline.py`'s `match_memories` now takes `query_embedding halfvec(3072)` and computes `memories.embedding::halfvec(3072) <=> query_embedding` in both the projection and the ORDER BY, so the distance expression matches the `memories_embedding_halfvec_hnsw_idx` expression index from `0016` and the function can use it — the exact follow-up 0016's own header deferred. The two "ported VERBATIM" notes in the file were amended to record the deliberate divergence. The baseline's `downgrade()` (raise-only) is untouched, `repository.py` was not touched (the app-side rewrite is the retrieval teammate's), and no new migration file was created. Note for the lead: editing the baseline only affects fresh databases — existing environments keep the vector-typed function until the `CREATE OR REPLACE` is re-applied or the app-side rewrite stops calling it, so the deploy runbook needs one of those two coordinated with the repository.py change.

## docker-compose.dev.yml

Left alone on purpose: the dev stack runs Postgres + Redis + Adminer only (host-run backend, no redis eviction flags, no worker replicas), so there is no prod topology to mirror there.

## Evidence

- `cd backend && .venv/bin/pytest -m "not integration"` → **2274 passed, 42 skipped, 0 failed** (the baseline has grown past 2243 with teammates' in-flight tests; earlier runs during this session failed only inside `app/graph/factories.py` and `app/graph/tools/_shared.py` while those teammates were mid-edit — both files now parse and their lanes pass).
- `.venv/bin/ruff check .` → clean.
- `docker compose -f backend/docker-compose.yml config` (dummy secrets) → parses; rendered per-service env confirmed web 8/4, all five workers 4/2, `worker-maintenance` consuming `maintenance`.
- New/updated tests: `tests/test_core_cache.py` pins flush-on-miss (fresh generation > 10⁹, stable and persisted across reads, present counter returned verbatim, outage never returns "1", bump-on-absent never restarts small), `tests/test_worker_enqueue_utils.py` pins the followup/maintenance default bounds (rejection at depth, explicit max_depth wins, 0 disables).

## Deployment note

Code-only changes; nothing deployed, nothing committed. Everything above activates on the next `make deploy`: the redis policy on container recreate, pool sizing on service recreate, tick re-registration on the first new-color boot, and the migration text on the next fresh-database build. During the blue/green flip window the old color may briefly re-register ticks on `followup`; the reconcile tick's Redis non-reentrancy lock dedupes concurrent execution, and the new color's next boot re-corrects the schedule. If `/opt/vfic/.env` carries `DB_POOL_SIZE`/`DB_MAX_OVERFLOW` (the dev `.env` does), the explicit per-service entries now override them for every resident service; the scheduler container inherits whatever `.env` says but never opens a DB connection.

## Unresolved questions

1. CLOSED (follow-up commit `eb0f5872`): `main.py` `/metrics` now lists `maintenance` in the queue tuple, so ops sees the new queue's depth.
2. Existing-database story for the `match_memories` rewrite (see PERF-08 above): manual `CREATE OR REPLACE` re-apply at deploy time, or rely on the repository.py rewrite abandoning the SQL function — holding for the lead's runbook call in coordination with the retrieval teammate's landing.
3. CLOSED (follow-up commit `eb0f5872`): `reconcile_worker.enqueue_reconcile_tick_now` now enqueues its ops manual trigger onto `maintenance` (docstrings updated, routing pinned by a test), so a manual sweep runs on the maintenance worker instead of head-of-line-blocking nudges; it also inherits the `maintenance_queue_max_depth` bound automatically.

Follow-up note on shared-tree commits: the four ticket-scoped changes landed as `a23033a1`, `f7e86594`, `13e78e41`, `fb9632e2`, plus `eb0f5872` for the two loose ends. Where a file carried both my hunks and a teammate's in-flight work (main.py middleware, reconcile_worker lock-CAS, config.py validator), the commit was staged from an intermediate state containing only my hunks; the teammates' work remains uncommitted in the tree for them.
