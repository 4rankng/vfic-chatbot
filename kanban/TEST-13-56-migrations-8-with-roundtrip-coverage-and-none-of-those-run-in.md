---
id: TEST-13
title: "56 migrations, ~8 with roundtrip coverage, and none of those run in CI"
severity: medium
area: testing
labels: [testing, ops]
effort: L
status: todo
found: 2026-09-24
---

# TEST-13 — 56 migrations, ~8 with roundtrip coverage, and none of those run in CI

**Severity:** medium · **Area:** testing · **Effort:** L · **Labels:** testing, ops

## Problem

The Alembic history holds 56 revisions, of which only about eight have any forward/backward roundtrip test, and none of those eight are reachable in CI. Because the blue/green flow runs `alembic upgrade head` against production and one Makefile target explicitly accepts downtime for non-additive migrations, a wrong `downgrade()` is discovered during a rollback.

## Evidence

- `backend/alembic/versions/` holds 56 files (`0001_baseline` … `0054_channel_account_projects`, plus `091e7edc9f76_merge_*`).
- Roundtrip/downgrade coverage exists for 0042 (`backend/tests/integration/test_installation_migration_roundtrip.py:37-105`), 0045 (`test_runtime_authority_stamp_migration.py:39-148`), 0047 (`test_canonical_channel_identity_migration.py:117-420`), 0049 (`test_adapter_persona_assignment_migration.py:35-98`), 0050 (`test_data_ingestion_recovery_migration.py:49`), 0051 (`test_bot_run_decision_trace_migration.py:21`), 0052 (`test_single_page_external_source_sync_migration.py:36`) and project-knowledge (`test_project_knowledge_migration.py:39-66`).
- No forward/backward test exists for 0041, 0043, 0044, 0046, 0048, 0053, 0054, nor for any of 0001–0040.
- All eight are unreachable in CI per TEST-01, while `backend/Makefile:155` (`deploy-breaking`) accepts downtime specifically for non-additive migrations.
- Where the tests do exist they are strong: `test_canonical_channel_identity_migration.py:402` proves downgrade fails closed when Messenger rows exist, and `test_project_knowledge_migration.py:39` seeds pre-0047 data before upgrading.

## Impact

A broken `downgrade()` is only discovered during a production rollback — the worst possible moment — and the deploy flow upgrades to head on every release.

## Suggested fix

Add one parametrized test that walks every revision: `upgrade <rev>` → `downgrade -1` → `upgrade head`, asserting `alembic heads` is singular and the expected tables and columns exist at each step, and asserting that `downgrade` raises for intentionally irreversible migrations rather than silently no-op'ing. It is a single file reusing `integration_database`.

---

_From the read-only tech-debt audit of 2026-09-24 (HEAD `923b1d3f`). No code was changed by the audit; all claims are grounded in the cited `path:line` locations._
