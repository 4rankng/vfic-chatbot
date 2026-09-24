---
id: OPS-08
title: "Worker healthchecks only ping Redis, so a wedged worker reports healthy forever"
severity: high
area: ops
labels: [ops, reliability]
effort: M
status: todo
found: 2026-09-24
---

# OPS-08 — Worker healthchecks only ping Redis, so a wedged worker reports healthy forever

**Severity:** high · **Area:** ops · **Effort:** M · **Labels:** ops, reliability

## Problem

Every worker and scheduler healthcheck is a Redis `ping()`. That proves the Redis client works, not that the worker consumes its queue, so a worker whose work loop has hung stays `healthy`, is never recycled by `restart: unless-stopped`, and passes the deploy's service count assertion.

## Evidence

- `backend/docker-compose.yml:101,140,160,178` — every worker/scheduler healthcheck is `python -c "import os,redis; redis.from_url(os.environ['REDIS_URL'], …).ping()"`.
- `backend/docker-compose.yml:84-96` — `worker-chatbot` runs at `replicas: 3`.
- `backend/scripts/bg_deploy.sh:96-118` — `require_running_service_count` passes a wedged-but-healthy worker; `:120-135` already asserts `total_workers >= 5`, so the RQ registry primitive is available.
- `backend/workers/reconcile_worker.py:9-12` — the only recovery path, re-enqueuing lost turns on the `recovery` queue after a ~60s scan plus 120s grace.

## Impact

A worker that has lost its work loop (thread hung, Redis connection fine, queue silently backing up) is `healthy` forever, so candidate turns queue or get reconciled late (~3-4 min) with no operator signal — the exact failure the 2026-09-22 recoveries were about.

## Suggested fix

Make the worker healthcheck assert liveness of the loop, not the socket: write a heartbeat key from the worker's main loop (or use RQ's worker registry) and have the healthcheck assert `Worker.all(connection=…)` includes this hostname with a fresh heartbeat timestamp.

## Notes

Merge with OPS-06 — this is the "wedged worker" row of its detection table.

---

_From the read-only tech-debt audit of 2026-09-24 (HEAD `923b1d3f`). No code was changed by the audit; all claims are grounded in the cited `path:line` locations._
