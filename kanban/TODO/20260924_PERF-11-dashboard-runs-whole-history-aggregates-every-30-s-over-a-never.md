---
id: PERF-11
title: "Dashboard runs whole-history aggregates every 30 s over a never-pruned `bot_runs` table"
severity: medium
area: performance
labels: [performance, ops]
effort: M
status: todo
column: TODO
opened: 2026-09-24
---

# PERF-11 — Dashboard runs whole-history aggregates every 30 s over a never-pruned `bot_runs` table

**Severity:** medium · **Area:** performance · **Effort:** M · **Labels:** performance, ops

**Trạng thái:** TODO

## Problem

The dashboard's summary and latency queries aggregate every `bot_runs` row with no time predicate, and one counter scans `conversations` on an unindexed predicate. The rows are never pruned — the retention worker only nulls `decision_trace` — so the cost grows every month.

## Evidence

- `backend/app/services/dashboard/repository.py:88-99` — `bot_run_summary` does `count(*)`, four `FILTER` counts and `avg(ended_at - started_at)` over all `bot_runs` rows with no time predicate.
- `backend/app/services/dashboard/repository.py:203-217` — `bot_run_p95_latency` takes `percentile_cont(0.95)` over 7 days; `:220-228` — `recent_turns_count`; `:194-201` — `active_turns` is `count(*) FROM conversations WHERE bot_locked_until > now()` with no supporting index.
- `backend/app/services/dashboard/service.py:54-90` — 13 sequential awaits per cache miss; `:38-39` — the 30 s cache applies only in production.
- `backend/app/workers/decision_trace_retention_worker.py:31-46` — only nulls `decision_trace` after 30 days; the row itself (one per turn) persists indefinitely.

## Impact

Every 30 s per viewer scope: a full-history aggregate over a monotonically growing audit table plus an unindexed `count(*)`, all competing with live turns for the same 2 vCPUs. This is background load that degrades every month.

## Suggested fix

Bound `bot_run_summary` to a window (`started_at > now() - interval '24 hours'`, covered by `bot_runs_started_at_idx` from migration 0033) or maintain rolling Redis counters updated where the `BotRun` is written; merge the five low-cardinality `_scoped_scalar` counts into one round trip; raise the dashboard TTL to 60 s (the frontend polls at 30 s, so a 60 s TTL halving the compute cost is invisible). The metric semantics change from all-time to 24 h and must be reflected in the API field names/labels.

---

_Opened 2026-09-24 from the read-only tech-debt audit (HEAD `923b1d3f`). No code was changed by the audit; every claim is grounded in the cited `path:line` locations._
