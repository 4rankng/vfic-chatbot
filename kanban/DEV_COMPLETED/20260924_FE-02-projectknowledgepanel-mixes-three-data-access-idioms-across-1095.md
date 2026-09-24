---
id: FE-02
title: "ProjectKnowledgePanel mixes three data-access idioms across 1095 LOC and 21 useState"
severity: high
area: frontend
labels: [tech-debt]
effort: L
status: dev-completed
column: DEV_COMPLETED
opened: 2026-09-24
---

# FE-02 — ProjectKnowledgePanel mixes three data-access idioms across 1095 LOC and 21 useState

**Severity:** high · **Area:** frontend · **Effort:** L · **Labels:** tech-debt

**Trạng thái:** DEV_COMPLETED

## Problem

`ProjectKnowledgePanel.tsx` is 1095 LOC whose `RagCategoriesPanel` alone is 623 LOC with 12 `useState`, and it talks to the same backend through three different idioms: a plain service facade driven by local state, react-admin's `useDataProvider`, and `useRefresh()` used to force react-admin refetches after facade writes. The two panels also duplicate hand-rolled `active`/`requestId` generation guards, and one effect disables `exhaustive-deps` because its loader is an unstable closure.

## Evidence

- `frontend/src/components/atomic-crm/projects/ProjectKnowledgePanel.tsx:358-980` — `RagCategoriesPanel` is 623 LOC with 12 `useState` `:360-373`; `SinglePagePanel` `:66-356` adds 9 more at `:69-77`.
- `frontend/src/components/atomic-crm/projects/ProjectKnowledgePanel.tsx:80-133` and `:414-503` — plain service-facade calls (`project-knowledge-service.ts`) driven by local `useState`.
- `frontend/src/components/atomic-crm/projects/ProjectKnowledgePanel.tsx:982-985` — `DiscoveryCardEditor` calls `useDataProvider<CrmDataProvider>()`, a second write path to the same resource; `useRefresh()` from ra-core at `:67`/`:984` forces refetches after the facade path writes.
- `frontend/src/components/atomic-crm/projects/ProjectKnowledgePanel.tsx:78`, `:375`, `:414-457` — two independent generation guards (`loadRequestRef`, `pollRef`) and two separate effects doing the same load.
- `frontend/src/components/atomic-crm/projects/ProjectKnowledgePanel.tsx:416-417` — `eslint-disable-next-line react-hooks/exhaustive-deps` because `loadCatalog` is an unstable closure.

## Impact

Two panels write the same resource through different paths, so cache coherence depends on manual `refresh()` calls. Every save and upload carries its own loading/error/notification triad, and the 623-LOC panel cannot be tested in isolation.

## Suggested fix

Introduce `useProjectKnowledgeCatalog(projectId)` (query + mutations, owns `pollUntilActive`), `useCategoryDraft(projectId, key)` and `useSinglePageDraft(projectId)`, with pure `CategoryEditor`, `SinglePageEditor`, `FaqAutoSyncSection` and `DiscoveryCardEditor` components. Route all writes through one layer — prefer the existing `project-knowledge-service` facade and delete the `useDataProvider` path, or the reverse — and do not keep both.

## Evidence log

- 0567d63b — `ProjectKnowledgePanel.tsx` 1095 → 316 LOC, 21 `useState` → 2; data layer to `projects/application/*` (catalog + cutover poll, category/single-page/discovery drafts), rendering to `projects/presentation/*`.
- One write path: the `project-knowledge-service` facade. `DiscoveryCardEditor`'s react-admin write became the port operation `updateProjectDiscoveryCard` (`PATCH /api/v1/knowledge/projects/{id}`, matching the backend `ProjectUpdate` schema). The two surviving `useRefresh()` calls are cache invalidation for the react-admin-cached project record, not a second write path.
- The `exhaustive-deps` disable and both hand-rolled generation guards are gone.
- Verified: `ProjectKnowledgePanel.test.tsx` 13/13 (harness-only change), `projects` suite 66 tests pass; a canary that broke one Vietnamese string flipped exactly the dependent test.

---

_Opened 2026-09-24 from the read-only tech-debt audit (HEAD `923b1d3f`). No code was changed by the audit; every claim is grounded in the cited `path:line` locations._
