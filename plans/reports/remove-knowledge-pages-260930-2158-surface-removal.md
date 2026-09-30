# Remove knowledge pages — report

Date: 2026-09-30. Owner decision: the standalone `knowledge_sources` and
`knowledge_bases` admin pages are not needed and bloat the frontend. Backend
API endpoints untouched. Controller commits.

## Dependency check (done BEFORE deletion)

- The only importer of modules from `knowledge/` / `knowledge-base/` outside
  those dirs was `capabilities/kernel/index.tsx` (resource registration).
  Verified by relative- and `@/`-alias import greps across `src/`.
- The projects feature is fully self-contained: `ProjectKnowledgePanel.tsx`
  and siblings import only their own `project-knowledge-*` modules and
  `../types`. `/api/v1/knowledge/...` strings there are backend URLs (staying).
- `personas/PersonaForm.tsx` fetches `useGetList("knowledge_bases")` — data
  fetching, not a page. `useGetList` does not consult `canAccess`
  (only `useCanAccess` in the vendored `app-sidebar` does), so removing the
  resource registration does not affect it. The `knowledge_bases` REST alias
  in `dataProvider.ts` `RESOURCE_PATH` is kept for exactly this call.
- `canAccess()`'s `availableResources` gate: no remaining code queries
  `knowledge_sources`, so dropping it from the runtime set is safe.

## Deleted (45 tracked files, both dirs incl. tests + screenshots)

- `frontend/src/components/atomic-crm/knowledge/` (knowledge_sources admin)
- `frontend/src/components/atomic-crm/knowledge-base/` (knowledge_bases admin)

Kept shared modules: none needed — nothing outside the two dirs imported
their modules. `dataProvider.ts` `RESOURCE_PATH` aliases kept as-is
(`knowledge_sources` → `knowledge/documents`, `knowledge_bases` →
`knowledge-bases`); the first is the documented REST alias pinned by
`dataProvider.test.ts`, the second is load-bearing for the persona KB picker.

## Edited

Source (removals only, no redesign):

- `capabilities/kernel/index.tsx` — removed both resource contributions, both
  navigation entries, both imports, unused `BookOpen`/`Library` icons.
- `capabilities/static-recruitment-runtime.ts` — dropped the two
  `kernel.resource.knowledge-*` RESOURCE_IDS and both knowledge
  NAVIGATION_IDS.
- `capabilities/types.ts` — `DestinationSection` loses `"knowledge"`.
- `layout/workspace-nav-model.ts` — dropped the "knowledge" section order +
  label (empty sections were already dropped at render time).
- `layout/Layout.tsx` — removed `isKnowledgeWorkspace` full-height branch.
- `layout/topbar/command-palette.tsx` — removed the "Tạo cơ sở kiến thức"
  action and the `Library` icon import.
- `providers/commons/canAccess.ts` — comment no longer cites
  `knowledge_sources` as an example resource.
- `providers/commons/vietnameseCrmMessages.ts` — removed the
  `resources.knowledge_sources` i18n block (there was never a
  `knowledge_bases` block).

Tests updated to the new expected surface (6 resources, 8 destinations):

- `capabilities/static-recruitment-runtime.test.ts`
- `capabilities/kernel/index.test.ts`
- `capabilities/kernel/navigation-contract.test.tsx`
- `capabilities/kernel/mobile-overflow-navigation.test.tsx`
- `layout/workspace-nav-model.test.ts` (fixture reworked off the removed
  section; the non-messages badge assertion now uses `users` → `/users`)
- `layout/workspace-shell.test.tsx`

Docs:

- `frontend/AGENTS.md` — overview count 8→6, resources table 8→6 rows,
  directory tree, the `RESOURCE_PATH` paragraph reworded (aliases remain;
  `knowledge_sources` no longer has a page), CSS-scoping container list now
  five screens.
- `docs/ops/qa-runbook.md` — removed the `#/knowledge_sources` route-table
  row, the `knowledge_sources` CRUD-safety mention, and the perf-probe route.
- `docs/development/code-standards.md` — RESOURCE_IDS count 8→6.
- Deliberately NOT touched: `docs/architecture/api.md` (documents the
  `RESOURCE_PATH` aliases, which remain in code),
  `docs/architecture/system-architecture.md` (backend data model),
  `docs/design/design-qa.md` (historical QA record — not rewritten).
- Root `AGENTS.md` does not name either resource (verified by grep) — no
  constitutional edit needed.

## Registry

`npm run registry:gen` after deletions: diff is **117 deletions, 0 additions**
(removal-only, verified). `npm run registry:check` passed (248 files) at that
point. NOTE: near the end of this task the parallel session created
`conversations/domain/conversation-channel-display.ts` (+ test, untracked) and
modified `ConversationList/ConversationShow.tsx`; a later registry:check run
now reports those as unpublished local dependencies. That drift belongs to the
conversations work, not this removal; the pre-commit hook runs
`registry:gen` again at commit time. I did not re-run gen to avoid folding the
other session's in-flight file into this diff.

## Verification (from frontend/)

- `npm run typecheck` — pass (0 errors), re-confirmed after formatting.
- `npm run test:unit:app` (full suite) — 749 passed / 4 failed / 753 total.
  All 4 failures are in files owned by the parallel `users-table-fix`
  session, which went in flight during this task:
  `kit/list-table.test.tsx > DEBUG dump DOM` (a debug test that throws by
  design; file carries 9 lines added by that session) and 3×
  `integrations/settings-workspace-layout.test.tsx` (40px vs 44px touch
  targets; the shared `conversations/inbox/tokens.css` is modified in flight
  by that session). Neither file nor its imports were touched by this
  removal. Isolated run of every suite this task touched — capabilities (all),
  `workspace-nav-model`, `workspace-shell`, `css-scoping`, `dataProvider` —
  9 files / 46 tests, all pass; re-verified after prettier (3 files / 11
  tests, pass).
- `npm run lint` — 0 errors, 36 pre-existing warnings (incl. the known
  `src/utils/is-react-component.ts` stale-disable warning).
- `npm run prettier` — all of this task's touched files pass; the remaining
  unformatted files flagged repo-wide belong to the parallel session's
  in-flight work (users/*, kit/*, conversations/*).
- `npm run registry:check` — passed post-gen (see registry note above re:
  later drift from the parallel session).
- `node scripts/check-doc-links.mjs` — pass (34 paths, 4 make targets).
- `css-scoping.test.ts` ratchet unaffected: it globs `*.css` and the deleted
  dirs contained none; count cannot move.

## Unresolved

- The 4 full-suite failures above are the parallel session's in-flight state;
  the controller should let that session finish (its pre-commit
  registry:gen/test run will then cover the combined tree).
