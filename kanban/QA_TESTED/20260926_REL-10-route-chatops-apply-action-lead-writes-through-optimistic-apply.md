---
id: REL-10
title: "Route ChatOps apply_action lead writes through optimistic_apply like set_stage/assign"
severity: low
area: reliability
labels: [concurrency, leads]
effort: S
status: done
column: QA_TESTED

opened: 2026-09-26
---

# REL-10 — Route ChatOps apply_action lead writes through optimistic_apply like set_stage/assign

**Severity:** low · **Area:** reliability · **Effort:** S · **Labels:** concurrency, leads

**Trạng thái:** DONE — implemented and committed 2026-09-27; see the sweep report for evidence

## Problem

Every LeadService mutator (set_stage, assign, update with version) goes through LeadRepository.optimistic_apply, a conditional `UPDATE ... WHERE version = current` that raises ConflictError on a lost race. The schedule_followup branch of ChatopsService.apply_action instead mutates lead attributes directly and commits with no version predicate, so a concurrent stage change or edit is not detected and two racing actions can both write version = N+1.

## Evidence

- backend/app/services/lead/chatops.py:90-95 — schedule_followup mutates `lead.next_action_at/updated_at/version += 1` as ORM attributes, then plain commit at :107
- backend/app/services/lead/service.py:242-246 — set_stage: `optimistic_apply(...)` else ConflictError
- backend/app/services/lead/service.py:212-216 — assign uses the same optimistic_apply + ConflictError pattern
- backend/app/services/lead/repository.py:154-168 — optimistic_apply is the documented 'optimistic-concurrency update + commit' primitive

## Impact

Two concurrent recruiter actions on the same lead (chatops action + stage change) can both succeed while the version counter stalls or regresses, so a subsequent legitimate edit is accepted against a stale precondition the system was designed to reject. Narrow window; silent corruption of the concurrency token rather than data loss.

## Suggested fix

Replace the direct mutation with `await self.leads.repo.optimistic_apply(lead.id, lead.version, next_action_at=due_at, version=lead.version + 1)` and handle ConflictError like set_stage, or delegate to a LeadService method that does. Fix together with REL-9 — same function.

## Notes

K-6 (fixed 2026-09-21) was the same invariant bypassed in another handler; this is the remaining site.

---

_Opened 2026-09-26 from the read-only tech-debt audit (HEAD `31d30377`). No code was changed by the audit; every claim is grounded in the cited `path:line` locations._
