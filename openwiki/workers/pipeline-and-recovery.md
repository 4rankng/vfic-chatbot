---
type: wiki
title: "RQ queues, scheduler ticks, and reconcile worker"
description: "Queue ownership (webhook_high, persistence_low, ingest, followup), per-tick registration in lifespan, reconcile sweep, and crash recovery model."
tags: [rq, workers, scheduler, reconcile, queues, crash-recovery, ticks]
verified:
  - by: openwiki/0.5.0
    at: 2026-09-08T09:17:45.993Z
sources:
  - id: openwiki-source-6dcfc1451bcbf8009d0484a9
    resource: repo://backend/app/core/config.py
  - id: openwiki-source-55002f5b1d39cf35fd6d60e2
    resource: repo://backend/app/main.py
  - id: openwiki-source-020810ee0dc73020cf840ea1
    resource: repo://backend/app/workers/async_runner.py
  - id: openwiki-source-dea1526caa69004bfd74add9
    resource: repo://backend/app/workers/reconcile_worker.py
  - id: openwiki-source-45c65eccdd84c772a83cb91a
    resource: repo://backend/app/workers/scheduler_utils.py
  - id: openwiki-source-3641e44aef067384d4965781
    resource: repo://backend/docker-compose.yml
  - id: openwiki-source-7865fb2b5570e6ebb2f50ca8
    resource: repo://docs/deployment-guide.md
generated: { by: "claude-code", at: "2026-09-08T09:17:45.993Z" }
---

# RQ queues, scheduler ticks, and reconcile worker

TingHire's background work runs on RQ (Redis Queue). Four named queues isolate
work by latency sensitivity and volume. A scheduler container fires periodic
ticks, and a reconcile worker sweeps for lost turns after crashes.

## Queue topology

| Queue | Worker(s) | Purpose |
|---|---|---|
| `webhook_high` | `worker-chatbot` × 2 | Bot turns — latency-sensitive, must drain fast |
| `persistence_low` | `worker-persistence` × 1 | Post-send persistence, enrichment, lead extraction |
| `ingest` | `worker-ingest` × 1 | Knowledge document ingestion (parse → chunk → embed) |
| `followup` | `worker-followup` × 1 | Proactive follow-up + reconcile sweep |

Replica counts are intentional:
- **2 × worker-chatbot**: the webhook ack must return in <1s; two replicas
  handle burst traffic without queueing
- **1 × each for persistence/ingest/followup**: these are throughput-bound,
  not latency-sensitive; one replica keeps resource usage low on the 2-vCPU
  droplet

## Async runner (`backend/app/workers/async_runner.py`)

RQ calls job functions synchronously. `run_async(awaitable)` runs the
awaitable on a process-local event loop. The loop is created once per worker
process and reused across jobs — async clients and SQLAlchemy engines stay
bound to a stable loop instead of being recreated per job.

`_shutdown_loop` (registered via `atexit`) drains pending tasks (5s deadline),
shuts down async generators, disposes LLM client cache, database engines, and
HTTP clients. Each resource cleanup is isolated — one failure does not block
the next.

## Tick registration (`backend/app/workers/scheduler_utils.py`)

### The duplicate-tick bug

`rq-scheduler` assigns a random id when `schedule()` is called without an
explicit `id`. Calling it on every web-container boot stacked a NEW recurring
job each time — the scheduled set grew to ~12 copies per tick and every copy
fired on its own interval, over-running both ticks ~12×.

### `register_unique_tick(scheduler, func, interval)`

Fixes the bug by:
1. Scanning all existing scheduled jobs for ones targeting `func`
2. Cancelling every match (clears legacy random-id duplicates)
3. Registering a single job with a stable id `vfic-tick-{func.__name__}`

Later boots re-score the same sorted-set member instead of appending another.

### `register_unique_cron_tick(scheduler, func, cron_string)`

Same pattern but for wall-clock-pinned schedules. Uses `scheduler.cron()`
instead of `scheduler.schedule()`. The cron expression is a 5-field UTC
expression parsed by `python-crontab`. Advantage over interval: a mid-day
web-container restart no longer pushes the next run out by a full interval.

## Registered ticks (in `main.py` lifespan)

| Tick | Interval/cron | Queue | Purpose |
|---|---|---|---|
| `run_proactive_followup_tick` | 1800s (30 min) | followup | Scan eligible conversations, enqueue per-lead proactive jobs |
| `run_reconcile_tick` | 60s | followup | Sweep for lost/stuck bot turns |
| `run_outbound_dispatch_tick` | 60s | persistence_low | Dispatch PENDING outbox rows, finalize stale SENDING rows |
| `run_decision_trace_retention_tick` | 86400s (daily) | persistence_low | Clear old decision_trace JSONB |
| `run_single_page_external_source_sync_tick` | cron `0 20 * * *` | ingest | Daily external-source sync at 03:00 ICT |

Each tick uses `register_unique_tick` or `register_unique_cron_tick` so
exactly one copy exists. Failure to register any tick is logged as non-fatal
so it cannot block web startup.

## Reconcile sweep (`backend/app/workers/reconcile_worker.py`)

The reconcile sweep is the primary reliability guarantee: regardless of *how*
a turn was lost (OOM kill, SyntaxError, deploy force-recreate,
exception-to-failed-queue, enqueue-fail-after-dedup), the sweeper detects and
recovers within one sweep cycle (~60s scan + 120s grace ≈ 3-4 min total
recovery).

### Non-reentrancy guard

`_RECONCILE_TICK_LOCK` is a Redis `SETNX` key with 300s TTL. If a prior tick
is still running, the new one skips silently.

### Sweep logic (`_sweep`)

1. Opens a `worker_session` and calls `repo.find_reconcile_candidates(now, grace_seconds, max_age_seconds, stale_lock_seconds, limit)`
2. For each candidate, classifies into one of:
   - **stale_pending**: PENDING message older than `reconcile_grace_seconds`
     (120s) — re-enqueue via `enqueue_chat_run`
   - **unanswered_inbound**: newest message is from the candidate, no bot
     reply within grace — re-enqueue
   - **stale_lock_breakable**: lock heartbeat older than
     `chat_turn_job_timeout` — force-break the lock and re-enqueue
   - **stale_send_unknown**: SENDING state older than grace — mark as
     `SEND_UNKNOWN` for audit
   - **skipped_locked**: valid lock held — skip (log for observability)
3. Each re-enqueue uses the existing `enqueue_chat_run` path
4. Redis counters track outcomes for the `/metrics` endpoint

### Safety invariants

- `acquire_lock` is taken *before* touching any PENDING row — overlapping
  ticks cannot double-enqueue
- `reconcile_grace_seconds` (120s) MUST exceed `chat_turn_job_timeout` (60s):
    a candidate only surfaces after RQ has killed the job, so a stale-heartbeat
    lock is always a dead worker, never a live turn
- A completed turn (sent OR suppressed) leaves `BOT/SENT` or `BOT/SUPPRESSED`
  as the newest message → excluded from sweep

### Observability counters

| Redis key | Purpose |
|---|---|
| `reconcile_re_enqueues_total` | Turns recovered by re-enqueue |
| `reconcile_stale_pending_total` | Stale PENDING messages found |
| `reconcile_unanswered_inbound_total` | Unanswered candidate messages |
| `reconcile_skipped_locked_total` | Skipped (valid lock held) |
| `reconcile_enqueue_failed_total` | Re-enqueue failures |
| `reconcile_unknown_send_outcome` | Unknown send outcomes |
| `reconcile_stale_lock_broken` | Force-broken stale locks |
| `reconcile_unanswered_gauge` | Current unanswered count |

All counters are read by `GET /metrics` in `main.py`.

## Chatbot worker (`backend/app/workers/chatbot_worker.py`)

`enqueue_chat_run(conversation_id, message_id, trace_id, ...)` enqueues a bot
turn onto `webhook_high`. The worker:

1. Opens a `worker_session`
2. Builds `GraphDeps` via `build_deps(db)`
3. Calls `run_turn(conv, message, deps)` — the LangGraph pipeline
4. The RQ job timeout is `chat_turn_job_timeout` (60s) — must be < `bot_lock_ttl_seconds` (180s) so RQ kills a stuck turn before its lock auto-expires

## Persistence worker (`backend/app/workers/persistence_worker.py`)

Runs on `persistence_low`. Handles post-send persistence (message delivery
state updates), OA profile enrichment, and lead extraction. Isolated from
`webhook_high` so slow enrichment never blocks bot turns.
