---
id: PERF-18
title: "Batch the per-sibling revision fetch in _reapply_active_sibling_projections (io-in-loop)"
severity: medium
area: performance
labels: [io-in-loop, knowledge]
effort: S
status: dev-completed
column: DEV_COMPLETED
opened: 2026-09-27
---

# PERF-18 — Batch the per-sibling revision fetch in _reapply_active_sibling_projections (io-in-loop)

**Severity:** medium · **Area:** performance · **Effort:** S · **Labels:** io-in-loop, knowledge

**Trạng thái:** DEV_COMPLETED

## Problem

category_projections.py's _reapply_active_sibling_projections issues one await self.db.get(KnowledgeCategoryRevision, ...) per sibling category inside its for loop (:143) — a classic N+1 on the database boundary, flagged by repowise at high confidence with loop magnitude growing with data. It runs on the category revision cutover path, so the query count scales with the project's category count exactly when an admin is mid-cutover.

## Evidence

- backend/app/services/knowledge/category_projections.py:143 — await self.db.get(KnowledgeCategoryRevision, sibling.active_revision_id) inside for sibling in siblings: (one DB round-trip per iteration)
- repowise opportunity perf2_30eeea1fc26b17caa2a2: io_in_loop, boundary db, execution context production, confidence high, effort S / benefit 2.8
- backend/app/services/knowledge/category_projections.py:135-141 — the siblings select already returns every row the loop needs keys from

## Impact

Cutover latency grows linearly with sibling categories; on a project with many categories the admin cutover request stacks dozens of sequential round-trips before the response resolves.

## Suggested fix

Collect sibling.active_revision_id keys before the loop and fetch once with select(KnowledgeCategoryRevision).where(<pk>.in_(keys)), then map by id. Validate result equivalence against the existing projection tests, and keep the None-guard for revisions deleted between the sibling fetch and the batch read.

## Notes

Adjacent to but distinct from ARCH-23: that card splits category_service.py, this one fixes a query shape in category_projections.py.

## Evidence log

- _reapply_active_sibling_projections now collects sibling.active_revision_id keys and fetches once via select(KnowledgeCategoryRevision).where(id.in_(keys)), mapped by id; the vanished-mid-read None-guard is preserved and the empty-sibling case issues no revision query.
- Regression test backend/tests/test_category_projections_sibling_batch.py (batched fetch + IN params + vanished-skip + zero-query when no siblings); full unit suite 2542 passed / 24 skipped.

---

_Opened 2026-09-27 from the read-only tech-debt audit (HEAD `d2e8889f`). No code was changed by the audit; every claim is grounded in the cited `path:line` locations._
