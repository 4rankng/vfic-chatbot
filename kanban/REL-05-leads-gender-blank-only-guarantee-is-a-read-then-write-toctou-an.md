---
id: REL-05
title: "leads.gender blank-only guarantee is a read-then-write TOCTOU and the write is unconditional"
severity: medium
area: reliability
labels: [reliability]
effort: S
status: done
found: 2026-09-24
---

# REL-05 — leads.gender blank-only guarantee is a read-then-write TOCTOU and the write is unconditional

**Severity:** medium · **Area:** reliability · **Effort:** S · **Labels:** reliability

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

---

_From the read-only tech-debt audit of 2026-09-24 (HEAD `923b1d3f`). No code was changed by the audit; all claims are grounded in the cited `path:line` locations._
