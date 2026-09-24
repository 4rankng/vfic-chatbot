---
id: OPS-07
title: "Blue/green deploy runs migrations with no pre-migration dump and no lock_timeout"
severity: high
area: ops
labels: [ops, reliability]
effort: S
status: in_progress
column: TODO
opened: 2026-09-24
---

# OPS-07 — Blue/green deploy runs migrations with no pre-migration dump and no lock_timeout

**Severity:** high · **Area:** ops · **Effort:** S · **Labels:** ops, reliability

**Trạng thái:** TODO

## Problem

`bg_deploy.sh` step 3 runs `alembic upgrade head` before the new colour boots, with no `pg_dump` immediately prior and no `lock_timeout`/`statement_timeout` on the migration connection. The only nearby backup is the OneDrive dump taken by `deploy-backend`, which plain `make deploy` does not run. The 240s health budget covers the web colour, not the migration step.

## Evidence

- `backend/scripts/bg_deploy.sh` step 3 — `docker compose run --rm --no-deps web-blue sh -c 'python -m scripts.widen_alembic_version && alembic upgrade head'`, with no dump immediately before it.
- `Makefile:54` — `deploy-backend` runs `release-check` + `backup`; `Makefile:37` — plain `make deploy` does not, so the closest dump can be days old.
- `backend/alembic/env.py:46-49` and `backend/alembic.ini` — set no `lock_timeout`/`statement_timeout`.
- `backend/scripts/bg_deploy.sh:170` — the 240s health budget covers the web colour only, not the migration step.
- `backend/alembic/versions/0017_replace_lead_stage_flow.py:48-51` — documents that `QUALIFIED`/`APPLIED`/`HIRED` collapsed irrecoverably into `REGISTERED` on upgrade, so its only rollback is a dump.

## Impact

(1) If a migration is destructive in one direction, the only rollback is a dump that may be days old. (2) A DDL lock queued behind a long-running query waits forever — `ALTER TYPE` and `ALTER COLUMN TYPE` need ACCESS EXCLUSIVE and nothing bounds the wait, so the deploy hangs indefinitely while Caddy still serves the old colour: no user-visible outage, but no progress and no timeout.

## Suggested fix

Add `pg_dump` to `backend/scripts/bg_deploy.sh` immediately before the migration step, keep the last N dumps, and set `lock_timeout=5s` plus a `statement_timeout` for the migration connection in `backend/alembic/env.py`. On lock timeout, fail the deploy loudly and leave the old colour serving.

## Notes

Merge with OPS-17 — the missing `lock_timeout` is what makes non-concurrent index DDL a deploy-stalling risk.

---

_Opened 2026-09-24 from the read-only tech-debt audit (HEAD `923b1d3f`). No code was changed by the audit; every claim is grounded in the cited `path:line` locations._
