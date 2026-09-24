---
id: OPS-17
title: "Later migrations create indexes non-concurrently against live tables"
severity: medium
area: ops
labels: [ops, performance]
effort: S
status: todo
found: 2026-09-24
---

# OPS-17 — Later migrations create indexes non-concurrently against live tables

**Severity:** medium · **Area:** ops · **Effort:** S · **Labels:** ops, performance

## Problem

Five migrations after the baseline issue plain `CREATE INDEX`/`CREATE UNIQUE INDEX` on existing tables, unlike `0014` and `0016`, which correctly use `CREATE INDEX CONCURRENTLY` inside `op.get_context().autocommit_block()`. `bg_deploy.sh` runs migrations while the old colour keeps serving, so a slow lock turns into queued candidate writes.

## Evidence

- `backend/alembic/versions/0039_multi_vertical_ingestion_templates.py:152` (`CREATE UNIQUE INDEX uq_active_kb_version_per_project ON kb_versions`), `0031_conversation_seq_and_trace_id.py:52` (`ix_bot_runs_trace_id`), `0036_outbound_outbox.py:110` (`ix_outbound_outbox_pending_created`), `0009_feature_catalog_active.py:46`, `0017_replace_lead_stage_flow.py:43,75` (recreating `leads_stage_idx` right after an `ALTER TYPE`).
- `backend/alembic/versions/0014_retrieval_scaling_indexes.py:57-79` and `0016_query_perf_indexes.py:54-135` — the correct pattern (`CONCURRENTLY` inside `autocommit_block()`).
- `backend/alembic/env.py:46-49` and `backend/alembic.ini` — no `lock_timeout`, so nothing bounds the wait (see OPS-07).
- [INFERENCE] Table sizes in production are unknown (no DB access), so the lock impact is characterised as pattern risk rather than an active incident; no rewrite byte-size was measured.

## Impact

`CREATE INDEX` takes a write-blocking lock on its table, and `backend/scripts/bg_deploy.sh` runs migrations while the old colour serves, so a slow lock queues candidate writes. Today's tables (`kb_versions`, `bot_runs`) are not the hot path, but with no `lock_timeout` the next migration on `messages`/`leads`/`conversations` will stall the deploy silently.

## Suggested fix

Require `CONCURRENTLY` + `autocommit_block()` for all index DDL on existing tables, state it in `docs/code-standards.md`, and set `lock_timeout` on the migration connection (OPS-07). Because `CONCURRENTLY` leaves an INVALID index on failure, add a post-deploy check that no index has `indisvalid = false`.

## Notes

Merge with OPS-07 — the lock timeout belongs to the same migration path.

---

_From the read-only tech-debt audit of 2026-09-24 (HEAD `923b1d3f`). No code was changed by the audit; all claims are grounded in the cited `path:line` locations._
