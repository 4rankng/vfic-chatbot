---
id: REL-05
title: "leads.gender blank-only guarantee is a read-then-write TOCTOU and the write is unconditional"
severity: medium
area: reliability
labels: [reliability]
effort: S
status: qa-tested
column: QA_TESTED
opened: 2026-09-24
---

# REL-05 — leads.gender blank-only guarantee is a read-then-write TOCTOU and the write is unconditional

**Severity:** medium · **Area:** reliability · **Effort:** S · **Labels:** reliability

**Trạng thái:** QA_TESTED

## Problem

The "only fill a blank gender" rule lives in the adapter as a read-then-write, while the SQL update itself has no guard — so a concurrent provider enrichment can be overwritten.

## Evidence

- `backend/app/recruitment/infrastructure/service_adapters.py:114-143` — `stored_gender()` reads, then `record_inferred_gender()` re-reads and calls `set_gender_by_id`.
- `backend/app/services/lead/repository.py:141-160` — `UPDATE leads SET gender = :gender WHERE id = :lead_id`, no `IS NULL`/blank guard; the docstring at `:142-153` acknowledges the guard lives in the adapter. `version`/`updated_at` are untouched.
- The provider path *is* atomic: `backend/app/services/profile_enrichment.py:287-312` uses `.where(..., _blank_column(Lead.gender))`.

## Impact

If OA profile enrichment commits `male` between the adapter's read and its write, the blank guard passes and the inferred value replaces it — the candidate is mis-addressed for the rest of the conversation, and because `version`/`updated_at` are untouched the recruiter console cannot show the value changed. With `override=True` it also overwrites a recruiter's recent CRM edit.

## Suggested fix

Push the guard into the statement: pass `override` down and add `or_(Lead.gender.is_(None), func.btrim(Lead.gender) == "")` when not overriding, and bump `updated_at` (plus `version` for the override case) so the console reflects it.

## Evidence log

- ee0e28e5 — blank-only guard moved into the UPDATE (+updated_at, version on override)
- tests/test_lead_gender_guard.py (8 tests) — guarded UPDATE, override wins, rowcount semantics
- QA 2026-09-24 (orchestrator, first-hand): unit 2299 passed + ruff clean; integration 130 passed (Postgres 16 disposable DB, alembic head); frontend tsc/eslint/vitest 593 green; e2e chromium 4 and Mobile Chrome 4 green against the real backend

---

_Opened 2026-09-24 from the read-only tech-debt audit (HEAD `923b1d3f`). No code was changed by the audit; every claim is grounded in the cited `path:line` locations._
