---
id: FE-15
title: "Dashboard derivations are recomputed on every render"
severity: medium
area: frontend
labels: [performance]
effort: S
status: todo
column: TODO
opened: 2026-09-24
---

# FE-15 — Dashboard derivations are recomputed on every render

**Severity:** medium · **Area:** frontend · **Effort:** S · **Labels:** performance

**Trạng thái:** TODO

## Problem

`RecruitingCommandCenter` runs `filterHumanInterventions`, `groupCandidatesByDay` and a `reduce` count inline on every render, including opening or closing the candidate dialog whose state lives in the same component subtree, every 30 s refetch, and every `isFetching` toggle. The grouping is non-trivial and runs over the whole candidate list, and `GroupedVirtuoso` depends on its output.

## Evidence

- `frontend/src/components/atomic-crm/dashboard/RecruitingCommandCenter.tsx:149-150` — `filterHumanInterventions(data?.immediate ?? [])` and `groupCandidatesByDay(candidatesQuery.data ?? [])` are plain statements in the render body.
- `frontend/src/components/atomic-crm/dashboard/RecruitingCommandCenter.tsx:556` — the candidate dialog's open/close state lives in the same component, so unrelated UI events re-run both derivations.
- `frontend/src/components/atomic-crm/dashboard/candidateDashboard.ts:187-191` — `groupCandidatesByDay` maps and groups the entire candidate list; `RecruitingCommandCenter.tsx:5` `GroupedVirtuoso` consumes those groups.
- Contrast with `deriveCacheDiscriminators` (`dashboard/recruitingCommandCenterLogic.ts`), which is already extracted, pure and consumed at `RecruitingCommandCenter.tsx:163`.

## Impact

O(n) grouping plus filter plus sort is re-executed for unrelated UI events; with a large candidate list that is visible jank on the landing page.

## Suggested fix

`useMemo` both derivations on `[data?.immediate]` / `[candidatesQuery.data]` and hoist the count into the same memo. Also stop `saveCandidateProfile` (`RecruitingCommandCenter.tsx:119`) refetching on the failure path, which doubles list traffic on every failed edit.

---

_Opened 2026-09-24 from the read-only tech-debt audit (HEAD `923b1d3f`). No code was changed by the audit; every claim is grounded in the cited `path:line` locations._
