---
id: PERF-12
title: "Three periodic ticks and the reconcile sweep share a single `followup` worker with no depth bound"
severity: medium
area: performance
labels: [performance, ops, reliability]
effort: S
status: done
found: 2026-09-24
---

# PERF-12 — Three periodic ticks and the reconcile sweep share a single `followup` worker with no depth bound

**Severity:** medium · **Area:** performance · **Effort:** S · **Labels:** performance, ops, reliability

## Problem

The reconcile tick, the outbound-dispatch tick and the proactive-nudge tick all register on the `followup` queue, which has a single replica, and the reconcile sweep also enqueues to it. Only `webhook_high` has backpressure.

## Evidence

- `backend/app/main.py:97-130` — `run_reconcile_tick` (60 s), `run_outbound_dispatch_tick` (60 s) and `run_proactive_followup_tick` (30 min) all register on `queue_name="followup"`.
- `backend/docker-compose.yml` — the `followup` queue gets a single `worker-followup` replica; `backend/app/workers/reconcile_worker.py:67` enqueues to the same queue.
- `backend/app/workers/reconcile_worker.py:107-190` — a tick loads up to `reconcile_batch_size=50` full Conversation ORM objects (`backend/app/services/conversation/repository.py:443-513` plus the selectin cascade) then opens a fresh session per candidate.
- `backend/app/workers/utils.py:70-78` — backpressure exists only for `webhook_high` (`chat_queue_max_depth=40`); the `followup` queue has no depth bound.

## Impact

Head-of-line blocking: a backlog-driven reconcile (the 2026-09-22 class of incident) occupies the only slot every 60 s, delaying proactive nudges and outbound retries behind it, and vice versa. With `SimpleWorker` that single worker is the real capacity behind `sla_seconds` — three concurrent queued turns, not the six the config comment assumes.

## Suggested fix

Move the reconcile and outbound-dispatch ticks to their own single-replica worker on a `maintenance` queue, keep proactive nudges on `followup`, and give both a `max_depth`. Optionally raise `worker-chatbot` to 4 only after PERF-01, PERF-03 and PERF-06 land, since each replica multiplies per-turn query load. Queue names are already parameterised (`run_worker.py` takes positional queues).

## Notes

Deployment-file change (compose + one registration change) — approval gate. Same stale `config.py:56` "6 chatbot replicas" comment as PERF-07.

---

_From the read-only tech-debt audit of 2026-09-24 (HEAD `923b1d3f`). No code was changed by the audit; all claims are grounded in the cited `path:line` locations._
