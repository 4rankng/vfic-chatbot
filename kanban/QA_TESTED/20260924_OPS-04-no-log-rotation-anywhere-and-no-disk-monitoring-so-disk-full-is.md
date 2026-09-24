---
id: OPS-04
title: "No log rotation anywhere and no disk monitoring, so disk-full is an unalerted total outage"
severity: critical
area: ops
labels: [ops, reliability]
effort: S
status: qa-tested
column: QA_TESTED
opened: 2026-09-24
---

# OPS-04 — No log rotation anywhere and no disk monitoring, so disk-full is an unalerted total outage

**Severity:** critical · **Area:** ops · **Effort:** S · **Labels:** ops, reliability

**Trạng thái:** QA_TESTED

## Problem

`backend/docker-compose.yml` declares no `logging:`, `max-size` or `max-file` keys on any of its 12 services, and there is no `daemon.json` in the repo, so Docker's default `json-file` driver grows without bound. Structured JSON logging to stdout is the *only* observability, by design, and nothing monitors host disk.

## Evidence

- `backend/docker-compose.yml` — zero `logging:`/`max-size`/`max-file` keys across all 12 services; a grep over the whole file returns only `healthcheck` hits, and no `daemon.json` exists in the repo.
- `backend/app/core/logging.py:63-73` — structured JSON logging to stdout is the only observability path, by design (`docs/deployment-guide.md:444-446`).
- Unbounded log producers: 3× `worker-chatbot`, `worker-ingest`, `worker-followup`, `scheduler`, both web colours, `caddy` (access logs) and `postgres` (`backend/docker-compose.yml`).
- `worker-ingest` runs with a 3600s job timeout (`INGEST_JOB_TIMEOUT_SECONDS`) whose reconcile and LLM warning volume is unbounded (`backend/docker-compose.yml`).

## Impact

When the volume fills, Postgres cannot write WAL and the whole stack goes down — with no alert, because per OPS-06 nothing pages a human. Detection time for disk-full today is **unbounded**: a human has to run `df`.

## Suggested fix

Add a compose `x-logging` anchor (`driver: json-file`, `max-size: 10m`, `max-file: 3`) and attach it to every service in `backend/docker-compose.yml` — one change, immediate bound. Add a host cron that alerts on `df` > 80% and on `docker system df`.

## Notes

Merge with OPS-06 — the disk-full row of its detection table is this ticket.

## Evidence log

- 4825c714 — x-logging anchor attached to all 14 services (10 MB x 3 per container)
- scripts/ops-alerts.sh — disk >80/>95%, reclaimable Docker, /metrics thresholds, /health
- verified: yaml.safe_load parses; docker compose config -q clean with env set; bash -n
- QA 2026-09-24 (orchestrator, first-hand): unit 2299 passed + ruff clean; integration 130 passed (Postgres 16 disposable DB, alembic head); frontend tsc/eslint/vitest 593 green; e2e chromium 4 and Mobile Chrome 4 green against the real backend

---

_Opened 2026-09-24 from the read-only tech-debt audit (HEAD `923b1d3f`). No code was changed by the audit; every claim is grounded in the cited `path:line` locations._
