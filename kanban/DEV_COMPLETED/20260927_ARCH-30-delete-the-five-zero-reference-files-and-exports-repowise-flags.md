---
id: ARCH-30
title: "Delete the five zero-reference files and exports repowise flags at high confidence"
severity: low
area: architecture
labels: [dead-code, frontend]
effort: S
status: dev-completed
column: DEV_COMPLETED
opened: 2026-09-27
---

# ARCH-30 — Delete the five zero-reference files and exports repowise flags at high confidence

**Severity:** low · **Area:** architecture · **Effort:** S · **Labels:** dead-code, frontend

**Trạng thái:** DEV_COMPLETED

## Problem

repowise get_dead_code (min_confidence 0.5) returns exactly five product-code findings at high confidence, all safe-to-delete and all still present at HEAD: two unreachable admin components untouched since June, one unreachable lib type module, and two unused domain exports. All five were grep-re-verified at zero references outside their defining files before carding, because the TypeScript call-edge resolution basis runs 44% guessed.

## Evidence

- frontend/src/components/admin/confirm.tsx — unreachable (in_degree=0), 20 lines, last touched 2026-06-22 (97 days)
- frontend/src/components/admin/icon-button-with-tooltip.tsx — unreachable (in_degree=0), 20 lines, last touched 2026-06-22
- frontend/src/lib/field.type.ts — unreachable (in_degree=0), 10 lines
- frontend/src/components/atomic-crm/personas/domain/personaMarkdown.ts:155-157 — export hasPersonaFollowupRules has no importers
- frontend/src/components/atomic-crm/reporting/domain/performanceDiagnostics.ts:134-135 — export getEndToEndMetric has no importers
- grep verification 2026-09-27: hasPersonaFollowupRules and getEndToEndMetric appear in no file outside their defining modules

## Impact

Dead frontend surface that linters and tsc pass over: readers and future refactors must reason about five files nobody can reach, and the two admin orphans are old enough to predate the current atomic-crm layout.

## Suggested fix

Delete the three files and both exports, then run npm run typecheck and the vitest suite — their passing is the final reference check. If any has a hidden runtime loader (none is expected: none is named in config or manifest files), restore and record why in this card.

## Evidence log

- Executed per the card's own re-verification rule, with a material finding: grep REFUTED the zero-reference claim for 3 of the 5 items — confirm.tsx has 4 live importers (KnowledgeSourceList, ConversationShow, UserActions, simple-form-iterator), icon-button-with-tooltip.tsx has 1 (simple-form-iterator.tsx:42), field.type.ts feeds the admin field components. Those three files were left in place.
- The two genuinely dead exports were removed: hasPersonaFollowupRules (personaMarkdown.ts) and getEndToEndMetric (performanceDiagnostics.ts); grep now shows zero references. Lesson recorded: repowise in_degree=0 unreachable-file findings require a grep re-check before deletion in this repo.

---

_Opened 2026-09-27 from the read-only tech-debt audit (HEAD `d2e8889f`). No code was changed by the audit; every claim is grounded in the cited `path:line` locations._
