---
id: FE-21
title: "Fix orphaned poll chain in use-project-knowledge-catalog when two revisions are tracked"
severity: low
area: frontend
labels: [frontend, polling, teardown]
effort: S
status: dev-completed
column: DEV_COMPLETED
opened: 2026-09-26
---

# FE-21 — Fix orphaned poll chain in use-project-knowledge-catalog when two revisions are tracked

**Severity:** low · **Area:** frontend · **Effort:** S · **Labels:** frontend, polling, teardown

**Trạng thái:** DEV_COMPLETED

## Problem

The category revision poller schedules each hop with pollRef.current = window.setTimeout(...) and the cleanup clears only that single ref. When trackRevision is called twice (upload fails review, operator replaces the file), the second call overwrites pollRef while the first chain is still pending, so the first chain can no longer be cancelled: unmount or projectId change clears only the newest timeout and the orphaned chain keeps calling getProjectKnowledgeCategories and setCategories/notify for up to MAX_POLL_ATTEMPTS×POLL_INTERVAL_MS (~40 s). The loop also ignores tab visibility entirely.

## Evidence

- frontend/src/components/atomic-crm/projects/presentation/use-project-knowledge-catalog.ts:56-59 — poll() stores pollRef.current = window.setTimeout(...) on every hop, so the ref only ever names the most recently scheduled timeout
- frontend/src/components/atomic-crm/projects/presentation/use-project-knowledge-catalog.ts:89-95 — the unmount/project-change cleanup clears only pollRef.current, i.e. one chain
- frontend/src/components/atomic-crm/projects/presentation/use-project-knowledge-catalog.ts:97-106 — trackRevision() calls pollUntilActive() without clearing an in-flight chain, so upload followed by replace runs two concurrent poll loops
- frontend/src/components/atomic-crm/projects/presentation/use-project-knowledge-catalog.ts:60-62 — each hop calls loadCatalog() and setCategories() after unmount for an orphaned chain; the branches also notify() (:65-84), so a toast can surface after leaving the page

## Impact

After a quick upload-then-replace, every subsequent unmount/project switch leaves a loop polling getProjectKnowledgeCategories up to 20×2 s and firing a stray success/failure toast afterward; hidden tabs additionally poll when nothing is watching.

## Suggested fix

Store a generation/epoch counter (or clear pollRef at the top of pollUntilActive and check it inside each hop before rescheduling) so a new trackRevision cancels the previous loop; also skip scheduling when document.visibilityState is hidden and resume on visibilitychange, matching the ExternalSourceList convention.

## Notes

Bounded (MAX_POLL_ATTEMPTS = 20 at :26), hence low; same visibility-gating family as FE-20 — fix together.

## Evidence log

- Epoch-based chain cancellation in projects/presentation/use-project-knowledge-catalog.ts: a second trackRevision cancels the first chain; unmount/project switch kills the live chain and discards in-flight hop results; hidden tabs pause hops; processingKey resets on project change.
- Red-first proof: with the corrected {data,total} mock shape the orphan test failed pre-fix at 22 getCategories calls vs 2 expected (the orphan polled its full 40s budget after unmount); 5 tests green, projects suite 13 files / 77 tests pass.

---

_Opened 2026-09-26 from the read-only tech-debt audit (HEAD `31d30377`). No code was changed by the audit; every claim is grounded in the cited `path:line` locations._
