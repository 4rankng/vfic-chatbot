---
id: ARCH-16
title: "`services/installation/service.py` (1055 LOC) interleaves validation, lifecycle, projection and checksums"
severity: medium
area: architecture
labels: [tech-debt]
effort: M
status: qa-tested
column: QA_TESTED
opened: 2026-09-24
---

# ARCH-16 — `services/installation/service.py` (1055 LOC) interleaves validation, lifecycle, projection and checksums

**Severity:** medium · **Area:** architecture · **Effort:** M · **Labels:** tech-debt

**Trạng thái:** QA_TESTED

## Problem

Revision CRUD and validation, the authority-locked lifecycle transitions, runtime resolution and readiness, the admin/runtime projections and the checksum assembly all live in one module.

## Evidence

- `backend/app/services/installation/service.py:91,290` — `create_revision`, `validate_revision`; `:441,453,477,495` — `activate_revision`, `rollback_revision`, `suspend`, `resume`, with the authority lock at `:444,456,478,496`.
- `backend/app/services/installation/service.py:523,565,577,615,797,881` — `resolve_active`, `require_active`, `assert_current`, `runtime_stamp_is_current`, `_validation_is_current`, `_runtime_readiness`.
- `backend/app/services/installation/service.py:620,684,926` — `runtime_view`, `admin_view`, `_active_context`; `:219-256` — checksum assembly.

## Impact

This module is also the per-turn hot path (PERF-01), so its size and interleaving make the authority cost harder to reason about and every turn-latency change lands in a 1055-line file.

## Suggested fix

Natural seam: `installation/{lifecycle,validation,projection}.py`. `app/installation/domain/projection.py` already exists, so the projection half has a home; the lifecycle half is the part with the authority lock (`:444,456,478,496`) and belongs together.

## Notes

Hot-path coupling: PERF-01 proposes making `resolve_active()` cache-first in this same module.

## Evidence log

- QA 2026-09-24 (orchestrator, first-hand): unit 2299 passed + ruff clean; integration 130 passed (Postgres 16 disposable DB, alembic head); frontend tsc/eslint/vitest 593 green; e2e chromium 4 and Mobile Chrome 4 green against the real backend

---

_Opened 2026-09-24 from the read-only tech-debt audit (HEAD `923b1d3f`). No code was changed by the audit; every claim is grounded in the cited `path:line` locations._
