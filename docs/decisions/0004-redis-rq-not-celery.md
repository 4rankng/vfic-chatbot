# ADR-0004: Redis + RQ Over Celery for Background Jobs

- **Status:** Accepted
- **Date:** 2026-06-26
- **Decider:** Project lead

## Context

The platform needs background job processing for:
- Chat turns (webhook_high — highest priority, candidate is waiting).
- Candidate extraction after bot replies (persistence_low).
- Knowledge document ingestion (ingest).
- Proactive follow-up + reconcile sweeps (followup).

All jobs are currently async Python coroutines bridged to sync RQ workers via `workers/async_runner.py`.

Options considered: Celery, RQ (Redis Queue), Dramatiq, in-process asyncio tasks.

## Decision

Use **Redis + RQ** (`rq>=2.0`, `rq-scheduler>=0.14`) for background job processing.

Key reasons:
- **Lower latency.** RQ is lighter than Celery — no broker abstraction layer, no worker warmup overhead. For chat turns where the candidate is waiting, every millisecond matters.
- **Simpler.** RQ's API is minimal: `enqueue()`, `Worker()`. No Celery config files, no `celery beat` daemon (use `rq-scheduler` instead).
- **Redis already required.** Redis is used for cache, pub/sub, presence, and the LLM semaphore — adding a job queue on the same Redis instance is zero additional infrastructure.
- **Python-native.** RQ jobs are Python callables — no serialization format to learn.
- **Queue priority.** RQ supports multiple queues with worker assignment (`webhook_high`, `persistence_low`, `ingest`, `followup`).

## Consequences

- **Positive:** Minimal config. Fast worker startup. Easy to inspect jobs via RQ Dashboard (or Adminer for Redis). `rq-scheduler` handles periodic ticks (reconcile every 60s, proactive every 30min).
- **Negative:** RQ is sync-only — async jobs must be bridged via `workers/async_runner.py:run_async()`, which creates a new event loop per job. This adds minor overhead. Celery has better support for complex workflows (chords, chains), but we don't need them.
- **Neutral:** RQ jobs are not persistent across Redis restarts (jobs in-flight are lost). The reconcile worker (`workers/reconcile_worker.py`) mitigates this by re-enqueuing lost/stuck bot turns every 60s.

## Related

- Worker entry: `backend/app/workers/run_worker.py`
- Chat turn worker: `backend/app/workers/chatbot_worker.py`
- Reconcile worker: `backend/app/workers/reconcile_worker.py`
- Async bridge: `backend/app/workers/async_runner.py`
- Queue config: `backend/app/core/config.py` (`redis_url`)
- [docs/system-architecture.md](../system-architecture.md) §4 (RQ queue model), §5 (Reconcile worker)
- [standards/performance.md](../../standards/performance.md) — queue model table
