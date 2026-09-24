---
id: REL-02
title: "Blocking synchronous Redis runs on the event loop in LLM telemetry and the semaphore release"
severity: high
area: reliability
labels: [reliability, performance]
effort: S
status: qa-tested
column: QA_TESTED
opened: 2026-09-24
---

# REL-02 — Blocking synchronous Redis runs on the event loop in LLM telemetry and the semaphore release

**Severity:** high · **Area:** reliability · **Effort:** S · **Labels:** reliability, performance

**Trạng thái:** QA_TESTED

## Problem

Per-LLM-call counters and the semaphore release use the synchronous Redis client inline in async code — exactly the pattern `backend/app/core/security.py` documents as forbidden and correctly avoids everywhere else.

## Evidence

- `backend/app/graph/clients.py:142-160` `_record_llm_latency` (sync pipeline), called at `:1103` and `:1371` inside the async agent loop; `:163-175` `_record_llm_429`.
- `backend/app/graph/usage.py:113-147` `record_token_usage` — sync pipeline per LLM response.
- `backend/app/graph/llm_semaphore.py:61-104` `_ensure_tokens` (sync `llen`/`rpush`) from `__aenter__`, and `:106-125,178-181` `__aexit__` sync `rpush`+`llen` — while acquire at `:159` correctly uses `run_in_executor`. The class is internally inconsistent.
- Same class elsewhere: `backend/app/services/dashboard/service.py:274-280,304-331` (sync Redis from `async def`), `backend/app/workers/chatbot_worker.py:508-523` (queue-depth read per turn).
- Correct pattern already in-repo: `backend/app/core/ops_health.py:12-13`, `backend/app/main.py:270-280`.

## Impact

4–12 blocking round trips per turn inside the loop of the process that also serves webhook acks and inline web-chat turns. Invisible with a healthy local Redis, which is why it survived review; any Redis latency (RDB fork, memory pressure, AOF fsync) is added directly to every concurrent request, and a hung Redis blocks the loop until socket timeout instead of yielding to `asyncio`.

## Suggested fix

Move the counters and the semaphore release onto the async client (`app/core/redis.py:get_redis()`) — they are fire-and-forget, so this is a drop-in — or wrap in `asyncio.to_thread`. Use `asyncio.to_thread` for the dashboard's sync-only reads. Also replace the deprecated `asyncio.get_event_loop()` at `backend/app/graph/llm_semaphore.py:159` with `asyncio.get_running_loop()`.

## Evidence log

- 7659a35c — telemetry on the async client, semaphore ops via to_thread, get_running_loop()
- tests/test_llm_semaphore.py (token ops never on the loop), tests/test_usage.py
- QA 2026-09-24 (orchestrator, first-hand): unit 2299 passed + ruff clean; integration 130 passed (Postgres 16 disposable DB, alembic head); frontend tsc/eslint/vitest 593 green; e2e chromium 4 and Mobile Chrome 4 green against the real backend

---

_Opened 2026-09-24 from the read-only tech-debt audit (HEAD `923b1d3f`). No code was changed by the audit; every claim is grounded in the cited `path:line` locations._
