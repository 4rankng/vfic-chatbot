---
id: FE-13
title: "The layered slice pattern covers 6 of ~22 features, and the two worst god files are unlayered"
severity: medium
area: frontend
labels: [tech-debt]
effort: L
status: todo
column: TODO
opened: 2026-09-24
---

# FE-13 — The layered slice pattern covers 6 of ~22 features, and the two worst god files are unlayered

**Severity:** medium · **Area:** frontend · **Effort:** L · **Labels:** tech-debt

**Trạng thái:** TODO

## Problem

`application`/`domain`/`infrastructure` folders exist only under six features, while sixteen others — including `integrations/` and `dashboard/` — are flat, so the two worst god files are exactly the two features that never got the pattern. Two compat re-export shims from an in-flight migration are also still standing, and feature tests sit at feature root rather than beside the code they cover.

## Evidence

- Layered: `conversations/`, `leads/`, `projects/`, `personas/`, `knowledge/`, `reporting/` — 6 of ~22 features.
- Flat (no layers): `integrations/`, `dashboard/`, `performance/`, `users/`, `knowledge-base/`, `automation/`, `settings/`, `layout/`, `misc/`, `kit/`, `root/`, `capabilities/`, `installation/`, `login/`, `providers/`, `hooks/`.
- `frontend/src/components/atomic-crm/conversations/conversation-list-filters.ts:1-15` re-exports from `domain/conversation-list-filters.ts`, and `conversations/presentation/use-conversation-realtime.ts:32-36` re-exports `messageOrdering` — migration residue, not duplication.
- Tests live outside the slices: `conversations/conversationDisplay.test.ts`, `conversations/chatRepository.test.ts`, `conversations/candidateNotes.test.ts` at feature root.

## Impact

The pattern was not applied where it was needed most, so the two largest components have no domain/application seam to extract along and no consistent home for pure logic or its tests.

## Suggested fix

Declare the rule in the folder context doc and either apply or drop it. At minimum give `integrations/` and `dashboard/` domain/application/infrastructure folders while executing FE-01 and FE-02, and finish the two re-export shims by updating the ~6 importers and deleting them.

## Notes

Layering in the direction that was audited is verified clean and is **not** a ticket: `components/ui/**` imports nothing from `components/admin/**` or `components/atomic-crm/**`; `components/admin/**` imports nothing from `atomic-crm` and depends only on `ui` + `lib` + `ra-core`; `src/lib/**` and `src/hooks/**` import no feature code (`ui/sidebar.tsx:7` imports only `@/hooks/use-mobile` + `@/lib/utils`); product code stays inside `atomic-crm/` with only the app shell (`main.tsx:6`, `App.tsx:1-6`) as an outside consumer.

---

_Opened 2026-09-24 from the read-only tech-debt audit (HEAD `923b1d3f`). No code was changed by the audit; every claim is grounded in the cited `path:line` locations._
