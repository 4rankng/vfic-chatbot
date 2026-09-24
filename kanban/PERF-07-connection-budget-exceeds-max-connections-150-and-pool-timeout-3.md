---
id: PERF-07
title: "Connection budget exceeds `max_connections=150` and `pool_timeout=30s` outlives the turn SLA"
severity: medium
area: performance
labels: [performance, reliability]
effort: S
status: todo
found: 2026-09-24
---

# PERF-07 — Connection budget exceeds `max_connections=150` and `pool_timeout=30s` outlives the turn SLA

**Severity:** medium · **Area:** performance · **Effort:** S · **Labels:** performance, reliability

## Problem

Every process uses the same 10+10 pool sizing while the compose topology has fewer processes than the config comment assumes, and the pool wait is three times the responsiveness SLA. The worst case therefore sits at the Postgres connection ceiling with no headroom.

## Evidence

- `backend/app/core/config.py:61-63` — `db_pool_size=10`, `db_max_overflow=10`, `db_pool_timeout=30`; `backend/app/core/db.py:18` — `pool_pre_ping=True` adds a liveness ping per checkout.
- `backend/app/core/config.py:54-58` — the sizing comment assumes "2 web + 6 chatbot replicas + followup/ingest/persistence/reconcile/scheduler (~13 processes)" and tells the reader to raise Postgres `max_connections` to ≥150.
- `backend/docker-compose.yml` — `web-blue` + `web-green` (one uvicorn each; `Dockerfile:28` sets `--workers 1`, so `WEB_CONCURRENCY=2` is inert), `worker-chatbot` × 3, `worker-persistence`, `worker-ingest`, `worker-followup` → 8 resident DB-touching processes; `postgres` runs with `-c max_connections=150`.
- `backend/app/reporting/infrastructure/performance_dashboard.py:20-24` — opens one session per read, up to 5 concurrent.

## Impact

Worst case 8 × 20 = 160 connections against a 150 ceiling before adminer or psql, i.e. zero headroom [EST]. When a pool is saturated a turn waits up to 30 s for a connection — three times the whole perceived-responsiveness SLA and past the point where the answer is useful — while holding the per-chat lock for `bot_lock_ttl_seconds=180`.

## Suggested fix

Set per-service pool env in compose (web `DB_POOL_SIZE=8`/`DB_MAX_OVERFLOW=4`; each worker `4`/`2` → 2×12 + 6×6 = 60 worst case, ~40% of the ceiling) and lower `db_pool_timeout` to ≤5 s so saturation fails fast into the recovery path instead of silently blowing the SLA. Workers run one job at a time (`SimpleWorker`), so 4+2 is ample.

## Notes

The comment at `backend/app/core/config.py:54-58` is stale: it sizes for "6 chatbot replicas" while `backend/docker-compose.yml` runs `worker-chatbot` × 3. Fix the comment in this change so the next sizing decision is not made on a topology that no longer exists.

---

_From the read-only tech-debt audit of 2026-09-24 (HEAD `923b1d3f`). No code was changed by the audit; all claims are grounded in the cited `path:line` locations._
