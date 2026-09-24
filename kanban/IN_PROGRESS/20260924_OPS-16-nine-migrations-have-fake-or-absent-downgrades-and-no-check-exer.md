---
id: OPS-16
title: "Nine migrations have fake or absent downgrades and no check exercises alembic downgrade"
severity: medium
area: ops
labels: [ops, tech-debt]
effort: M
status: in_progress
column: TODO
opened: 2026-09-24
---

# OPS-16 — Nine migrations have fake or absent downgrades and no check exercises alembic downgrade

**Severity:** medium · **Area:** ops · **Effort:** M · **Labels:** ops, tech-debt

**Trạng thái:** TODO

## Problem

Of 55 revisions plus one merge node, nine have `pass`, a `RuntimeError` or nothing in `downgrade()`. `release-check` asserts only that there is one head, no target, test or CI job runs `alembic downgrade`, and `make restore` stamps a historical dump as head with `|| true`, which hides drift.

## Evidence

- Fake or absent downgrades: `backend/alembic/versions/0001_baseline.py:622-626` (`raise RuntimeError`), `0007_conversation_semi_auto.py:22-25`, `0008_drop_bus_timetable_fn.py:26-30`, `0010_drop_dead_schema_objects.py:43-46`, `0018_backfill_conversation_leads.py:42-44`, `0024_delivery_read_states.py:28-31`, `0029_delivery_status_sending.py:30-33`, `0030_delivery_status_send_unknown.py:33-36` (all `pass`), and the merge node `091e7edc9f76_merge_0013_password_reset_otps_0013_.py:22-23`.
- `Makefile:19` — `release-check` asserts exactly one alembic head and nothing more; no target, test or CI job runs `alembic downgrade`.
- `Makefile:119-120` — `make restore` runs `alembic stamp head 2>/dev/null || true`, so a restored DB can claim a revision whose DDL it does not have and nothing will ever notice.
- `backend/alembic/env.py:6-7,26` — the ORM does not generate migrations and `target_metadata` is wired only for future autogenerate, so nothing mechanically checks `backend/app/models/` against the migrations.
- Well-behaved references to hold the line with: `0014_retrieval_scaling_indexes.py:57-87`, `0016_query_perf_indexes.py:54-162` and `0013_proactive_followup.py:44-49`.

## Impact

`alembic downgrade` is effectively non-functional for the 0001-0018 range and for four enum additions, so a future engineer discovering a bad deploy has to reconstruct DDL from git. Stamping a restored dump as head means the local DB can claim a revision whose DDL it does not match, invisibly.

## Suggested fix

For each `pass`, record the intent in a module-level comment plus a greppable marker — `# downgrade: INTENTIONAL_NOOP — <reason>` for 0007/0018/0024/0029/0030 and `# downgrade: FORWARD_ONLY — recover DDL from <path>` for 0008/0010. Add a CI step running `alembic upgrade head && alembic downgrade -1 && alembic upgrade head` on a throwaway Postgres, skipping the forward-only revisions via an explicit allow-list. Replace `alembic stamp head` in `Makefile:119-120` with a real `upgrade head`, or at minimum assert the stamped revision equals the dump's `alembic_version` row.

## Notes

Merge with OPS-20 — the `stamp head` line is one of the five low findings, and the revision-naming drift makes filename-to-revision correlation unreliable.

---

_Opened 2026-09-24 from the read-only tech-debt audit (HEAD `923b1d3f`). No code was changed by the audit; every claim is grounded in the cited `path:line` locations._
