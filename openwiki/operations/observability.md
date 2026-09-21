---
type: wiki
title: "Logging, structured context, and observability"
description: "setup_logging + request_id_ctx middleware, what gets logged and what never does (secrets/PII/message content), and how the decision trace ties into recruiter-visible bot_runs."
tags: [logging, observability, health, metrics, request-id, trace-id, structured-logging]
sources:
  - id: openwiki-source-09b84fd9a979d89a5af63d7f
    resource: repo://backend/app/api/performance.py
  - id: openwiki-source-770f01d7351c567fc93944dd
    resource: repo://backend/app/api/webhooks.py
  - id: openwiki-source-5031b1909db6babc7f500e8c
    resource: repo://backend/app/core/logging.py
  - id: openwiki-source-20a839164a70f3e4e1c3d2f1
    resource: repo://backend/app/core/ops_health.py
  - id: openwiki-source-c1d0d5024df77f0640b1eea9
    resource: repo://backend/app/graph/decision_trace.py
  - id: openwiki-source-55002f5b1d39cf35fd6d60e2
    resource: repo://backend/app/main.py
  - id: openwiki-source-15bad8919340e7784b0aa289
    resource: repo://backend/app/services/webhook.py
  - id: openwiki-source-54372f2d9834a49eaebe0cb9
    resource: repo://backend/app/workers/decision_trace_retention_worker.py
generated: { by: "claude-code", at: "2026-09-08T09:17:45.993Z" }
verified:
  - by: openwiki/0.5.0
    at: 2026-09-21T02:42:43.794Z
---

# Logging, structured context, and observability

TingHire emits structured JSON logs to stdout and exposes a small set of
unauthenticated health/metrics endpoints for ops monitoring. The logging
contract is explicit about what is recorded and what is never recorded.

## Structured logging (`backend/app/core/logging.py`)

`setup_logging()` installs a single `StreamHandler` on the root logger that
emits one JSON object per record to stdout. The `_JsonFormatter` includes:

| Field | Source |
|---|---|
| `ts` | `formatTime` (ISO 8601) |
| `level` | Log level name |
| `logger` | Logger name |
| `msg` | Formatted message |
| `request_id` | `request_id_ctx` context var |
| `trace_id` | `trace_id_ctx` context var |
| `exc` | Exception info (if any) |
| extra fields | Any non-standard `LogRecord` attributes (e.g. `llm_latency_ms`, `queue_depth`) |

Two loggers are suppressed to reduce noise:
- `uvicorn.access` → WARNING (redundant with request logging)
- `httpx` → WARNING (Zalo Bot Platform embeds the bearer token in the URL, so the transport logger must not disclose credentials)

### No-secrets-no-PII-no-message-content invariant

The structured logger **never** records:
- Secrets (API keys, tokens, encryption keys)
- PII (candidate names, phone numbers, email addresses)
- Message content (candidate or bot text)

Only request size and safe event metadata (e.g. `bytes=N`) are logged. The
webhook body is never logged because it can carry candidate text. Payload
stores changed keys only — never secret values.

## Request correlation (`request_id_ctx`)

`request_id_middleware` (in `backend/app/main.py`) stamps every HTTP request:

1. Reads `X-Request-Id` header or generates `uuid.uuid4().hex`
2. Sets `request_id_ctx` context var for the duration of the request
3. Echoes the id back as `X-Request-Id` response header
4. Resets the context var in `finally`

Every log line within the request carries `request_id` so a single user-visible
failure traces cleanly across the web process, RQ workers, and outbound Zalo
calls.

### Trace propagation across workers

`trace_id_ctx` is the logical turn trace. The webhook stamps the `request_id`
into the RQ job dict as `trace_id`; the worker re-stashes it in `trace_id_ctx`
(contextvars do not cross processes) so the same id flows through
RQ → LangGraph → Zalo send logs and onto `BotRun.trace_id`. Distinct from
`request_id` only inside the worker process (where the HTTP request is gone);
on the web process they carry the same value.

## Health and metrics endpoints

### `GET /health`

Returns `{"status": "ok", "env": "<app_env>"}`. Unauthenticated; used by
Caddy health checks and deployment smoke gates.

### `GET /metrics`

RQ queue depths + worker count — the signal for scaling worker-chatbot
replicas. Unauthenticated (internal ops endpoint, same trust level as `/health`).

Returns queue depth for each named queue (`webhook_high`, `persistence_low`,
`ingest`, `followup`), worker count, and reconcile canary counters
(`reconcile_re_enqueues_total`, `reconcile_stale_pending_total`,
`reconcile_unanswered_inbound_total`, `reconcile_skipped_locked_total`,
`reconcile_enqueue_failed_total`, `reconcile_unknown_send_outcome`,
`reconcile_stale_lock_broken`, `reconcile_unanswered_gauge`).

### `GET /health/queue`

Chat-path observability: queue depth, LLM latency, 429 count, worker
saturation. Unauthenticated. The snapshot lives in `app.core.ops_health` so
`/admin/performance` reuses the same live tiles without duplicating the
Redis/RQ reads.

Returns:
- `queue_depth` — `webhook_high` queue count
- `busy_workers` / `total_workers` — worker saturation
- `llm_avg_latency_ms` — average LLM call latency
- `llm_invokes_last_2m` — recent LLM invocation count
- `minimax_429s_last_1m` — recent 429 count
- `llm_token_usage` — today's token usage + estimated cost

### `GET /admin/performance` (admin-only)

Per-stage turn-latency metrics for the *Hiệu suất* panel. Aggregates
`BotRun.stage_timings` into p50/p95/p99 per stage, plus by-lane/outcome
counts and the slowest recent turns. Supports `?window=1h|24h|7d`.

The five time-windowed reads run concurrently via `asyncio.gather`, each on
its own `AsyncSession`. The assembled payload is cached in Redis for 30s,
matching the frontend `staleTime`.

### `GET /admin/performance/slos` (admin-only)

Latency + reliability SLOs: returns the 7 named SLOs with target + actual
p50/p95 + green/amber/red status. The `webhook_ack` SLO reads from a Redis
sliding window sampled at webhook ack time (no BotRun row exists that early).

## Decision trace and bot_runs

`DecisionTraceBuilder` accumulates per-node entries during a bot turn and is
finalized on send or suppression. The trace is bounded by:
- `MAX_DECISION_TRACE_EVENTS=64`
- `MAX_DECISION_TRACE_BYTES=128KiB` serialized JSON
- `MAX_MODEL_REASONING_CHARS=16KiB` per event

`BotRun` persists `decision_trace` as JSONB alongside `stage_timings` (per-stage
milliseconds). The retention tick clears `decision_trace` to NULL on
`Settings.decision_trace_retention_interval_seconds` (default 86400s = daily),
bounded by `decision_trace_retention_batch_size` (default 200) per tick and
`decision_trace_retention_days` (default 30).

`GET /api/v1/bot_runs` is visible to any authenticated user (admin + recruiter);
`GET /api/v1/bot_runs/{run_id}` is admin-only.

## Unhandled exception handler

`unhandled_exception_handler` catches every unhandled exception, logs it with
`request_id` via `logger.exception`, and returns a consistent Vietnamese 500
response (`"Đã có lỗi xảy ra, vui lòng thử lại sau."`) instead of a bare
English error. `HTTPException` has its own handler, so genuine business errors
(Vietnamese detail, intended status) are unaffected.
