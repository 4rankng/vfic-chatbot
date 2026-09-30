# Legacy single-page project → 12-category migration

Implemented the DIRECT_CONTEXT → 12-category migration path end to end: backend
gating, cutover mode flip, frontend migration affordance reusing the existing
brief-ingest chain, and tests in both lanes.

## Backend

- `backend/app/services/knowledge/category_authority.py`
  - New `require_category_project` gate (404 on missing project, no mode
    check); staged/clear/catalog/cutover/rollback now use it, so a
    DIRECT_CONTEXT project can stage, clear and cut over. `get_active_source`
    stays RAG-only by design.
  - `build_cutover_snapshot` captures `knowledge_base_mode`; cutover flips the
    linked knowledge base DIRECT_CONTEXT → RAG (the panel and the conversation
    routing both key on that mode — no new mode value invented), and rollback
    restores the captured mode. Pre-migration snapshots without the key roll
    back exactly as before.
  - Cutover and rollback bump `NS_PREAMBLE` — the routing catalog caches the
    KB mode under it.
- `backend/app/services/knowledge/category_service.py`
  - `stage_replacement` seeds all twelve `KnowledgeCategory` rows on a
    project's first write (a DIRECT_CONTEXT project owns none), mirroring the
    `base_service` bootstrap idiom; `list_catalog`/`clear` use the relaxed
    gate so the ingest chain's poll and the explicit clears work pre-cutover.

## Frontend

- `ProjectKnowledgePanel.tsx`: new `MigrationSection` in the DIRECT_CONTEXT
  branch (admin-gated via `canManageSources`, matching the admin-only clear +
  cutover endpoints). It reuses `BriefIngestSection` (progress board included)
  with a «Chuyển sang 12 danh mục — nhập từ tệp .md» button; after the chain
  lands it explicitly clears the `needsHuman` categories (cutover requires
  active-or-cleared for all twelve) and calls the cutover once, then
  `useRefresh()` so the panel re-renders as the catalog. Chain failure → no
  clear, no cutover.
- `use-project-ingest.ts`: `ingest` now resolves `true` only on the done state
  (failures report through `state`, not a throw). Additive — ProjectCreate
  ignores the return.
- New operations wired per the existing pattern: `clearCategory` +
  `cutoverCategories` through port → operations → service → HTTP adapter
  (confirmations `CLEAR` / `CUTOVER`), plus a `CategoryAuthorityState` domain
  type.

## Tests

- `backend/tests/integration/test_direct_context_category_migration.py` —
  real-DB journey: stage (seeds 12 rows, queue receipt, 404 kept), activation
  defers the legacy card, explicit clears, cutover (authority flag, card
  replacement, KB mode → RAG), rollback restores card + DIRECT_CONTEXT; plus a
  test that cutover still requires every category prepared.
- `backend/tests/test_direct_context_category_migration.py` — unit-lane proof
  (fake-session idiom from `test_brief_fixture_ingestion.py`) for the stage
  gate, seeding count, 404, the preserved RAG-only source read, and projection
  deferral.
- `frontend/.../ProjectKnowledgePanel.test.tsx` — the migration affordance
  renders for DIRECT_CONTEXT and not for RAG; a successful chain clears the
  brief's `needsHuman` categories in catalog order and calls the cutover
  exactly once before the refresh; a failed chain calls nothing.

## Verified gates

- Backend (integration file listed first — see the conftest note below):
  `python -m pytest tests/integration/test_direct_context_category_migration.py
  tests/integration/test_knowledge_ingestion.py tests/test_brief_fixture_ingestion.py
  tests/test_direct_context_category_migration.py -p no:randomly -q` → 25 passed;
  `tests/integration/test_project_category_activation.py` → 7 passed; ruff clean.
- Frontend: `npm run typecheck` clean; `npm run lint` 0 errors (my files lint
  clean); targeted `npm run test:unit:app -- --run
  src/components/atomic-crm/projects` → 185 passed.

## Concerns

1. Pre-existing pytest quirk (reproduced with only pre-existing files): an
   integration-lane file listed AFTER a unit-lane file in one invocation loses
   `tests/integration/conftest.py` fixtures — "fixture 'integration_session'
   not found" — so any new integration test appended last in the standard
   acceptance command errors out. My integration file therefore runs before
   the unit-lane files in the verified command; worth a separate look.
2. `npm run registry:check` currently fails on
   `conversations/domain/channel-icons.ts` — another agent's in-flight file; I
   created no new application files, so no manifest change is mine to make.
3. The migration affordance is admin-only (`canManageSources`), matching the
   admin-only clear + cutover endpoints; recruiters keep the unchanged
   single-page editor.
