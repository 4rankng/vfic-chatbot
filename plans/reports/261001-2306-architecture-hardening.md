# Architecture hardening

Date: 2026-10-01. Base: main `35d970689cbb092e4f9100f1e60305c9bd7505ed`.

## Outcome and approach

Retain the existing modular monolith and enforce its boundaries. The application already has domain/application/infrastructure slices, explicit graph ports, composition roots, feature-level frontend adapters and runtime contract tests. The concrete weaknesses were misplaced policy ownership, eager imports, incomplete guards and operation-lifetime ambiguity. A wholesale restructure would not resolve those causes more safely.

| Approach | Benefit | Cost and risk | Choice |
|---|---|---|---|
| Repair existing ownership and lifetime contracts | Makes extension points explicit; small, regression-testable changes | Existing compatibility facades remain | Implemented |
| Reshuffle all modules into a new common framework | Uniform directory structure | Broad churn and new indirection; moves behavior without proving it | Deferred |
| Split deployable services | Independent release/scaling boundaries | Distributed consistency and operational overhead for current single-tenant flows | No current evidence warrants it |

The recommended approach is the focused repair: preserve transaction, queue and provider contracts while making policy ownership and dependency direction executable.

## Proven causes and changes

1. **Realtime depended on HTTP transport.** Socket authentication imported the API auth dependency, and the architecture rule deliberately left this edge unenforced. Socket.IO now calls the same identity authenticator used by REST. Token-type, account-disable and token-version checks remain shared. The guard now rejects realtime-to-API imports. The typed decorator adapter retains all nine public custom events; entity authorization narrows UUID/integer contracts before viewer queries.
2. **Frontend primitive direction was documented but unenforced.** The scanner now rejects `ui` imports of admin/product code and admin imports of product code. Production edges have zero exceptions; component tests may use product locale fixtures, consistent with existing feature-test rules. Relative, alias and re-export forms are covered.
3. **KB policy had transport/service owners.** Category identity and ordered authoring metadata now live in framework-free project/knowledge domain modules. Ingest, templates, export, projections, retrieval checks and external sync share this registry. Record field and template names derive from ID, and invariant tests require exact schema coverage/order. Existing schema and contract imports remain compatible.
4. **Small helper imports loaded the persistence graph.** The knowledge package eagerly re-exported service/pipeline objects. A fresh-process regression proved retrieval category lookup loaded projections, SQLAlchemy, models and Pydantic. Existing sixteen public exports now resolve lazily, preserving identity, discovery and type-checking exports. Independent first-import checks passed for every symbol.
5. **Lead misses were confused with unperformed reads.** Runner and adapter contracts now distinguish an unresolved lookup from explicit `None`. Completed misses are reused throughout a turn; independent callers keep repository fallback. Real-adapter regressions cover both paths. Review caught a read-after-write issue: successful name capture could create/update a record while context still used the earlier miss/blank row. Only successful writes refresh context; failed refresh invalidates it so the next consumer retries. No-write misses retain a single lookup.
6. **Nested graph tools escaped the guard.** The recursive scanner found a TingTing tool importing a concrete service merely for a verification limit. That fixed policy moved to a framework-free integration domain module; the old service constant export remains compatible. Guards cover nested tools and import-time control flow.
7. **React render state was used as a mutation lock.** Category and discovery-card saves could both send two requests before `saving` rerendered. Both regressions failed with two backend mutations. The existing single-page editor's synchronous exclusion pattern now protects both flows, releases after failure and isolates project contexts. No speculative receipt or UI-layer refactor was added.
8. **Cutover snapshot typing lost a known value.** Adoption/supersession now retain the typed snapshot local through the existing transaction, avoiding nullable transport-state reads without changing SQL or commit behavior.

## Ownership and extension

- Category identity: `backend/app/project_knowledge/domain/category.py`; ordered definition/lookup: `domain/category_catalog.py`. Add identity, definition, typed schema and Markdown template together; category registry regressions enforce their coverage/order. Browser contracts remain typed and must be updated for any new public category.
- Bot stage dependencies: `backend/app/graph/ports.py` and recruitment application ports. Concrete wiring remains in existing factories/composition/adapters. Candidate lookup lifetime is declared in `recruitment/application/lead_lookup.py`.
- TingTing verification policy: `backend/app/integrations/tingting/domain.py`.
- Browser mutations: existing project presentation hooks use the same synchronous/context-aware operation pattern as the single-page editor.
- Guards: `backend/tests/test_architecture_boundaries.py` and `test_graph_import_guard.py`; runtime contract inventory must also pass.

This implements the existing accepted boundary decision and engineering constitution; it introduces no architectural layer, technology, plugin system or deployment topology requiring a new ADR.

## Verification

- Final backend unit run: `.venv/bin/python -m pytest -q -m 'not integration' --tb=short` — **3,322 passed, 37 existing skips, 295 integration cases deselected**. This fresh run includes the name-write context refresh follow-up.
- Complete backend run against an owned loopback PostgreSQL/pgvector container: `.venv/bin/python -m pytest -q --tb=short` — **3,613 passed, 37 existing skips**, including **295 PostgreSQL integration cases**. It started before four final name-refresh unit cases were added; the final unit run above revalidated all units after that fix. PostgreSQL code was unchanged by that graph-only follow-up. The fixture migrated and dropped its isolated database; the task-owned container was removed afterward.
- Frontend: `npm run test:unit:app -- --run` — **900 passed across 118 files**; focused changed-hook tests also passed. Existing React act warnings did not fail assertions.
- Type checks: all **22 changed backend source paths** passed Pyright with **0 errors/0 warnings**; frontend app TypeScript passed, Node TypeScript passed, and production build succeeded.
- Lint: whole backend Ruff passed; scoped frontend ESLint passed. Whole frontend lint passed with **0 errors/35 existing warnings** in unrelated vendored components/utility code.
- Build/runtime smoke: production bundle built; built login screen rendered with no page errors. Registry check verified 232 dependency paths.
- Independent review: shared authentication, nine Socket.IO handler registrations, scanner direction and lazy exports passed; all sixteen public KB exports were each exercised as a first import in fresh processes. Five name-write/context cases independently passed with one mutation per turn.
- Architecture/runtime inventory, source parsing, documentation routing and whitespace checks passed. The architecture exception allowlist remains empty. No new TODO/FIXME/HACK markers were introduced.
- Pre-fix failing regressions proved scanner gaps, the eager KB dependency load, duplicate saves and stale name context. The suspected ingest retry-counter bug was disproved and no change was made for it.
- Exact changed paths and portable artifact checks are in the full/incremental manifests.

Local evidence logs: `/tmp/vfic-architecture-backend-{all,units-final,types-final,lint}.log`, `/tmp/vfic-architecture-frontend-{all,lint}.log`, `/tmp/vfic-architecture-{build,smoke,registry,node-types}.log` and focused reviewer/agent logs. These machine-local logs are not included in the patch; results and test sources are included.

## Scope and limits

All earlier authorized recruitment, project KB, upload/export/template and responsive UI changes are preserved. No public HTTP response shape, route, queue, durable callable path, database schema, provider workflow or product copy changed in this architecture pass. No dependency additions, branch, commit, push, PR, merge or deployment.

The static guards certify their specified dependency matrix, including the newly covered seams; computed imports remain subject to review. Existing migration debt noted in the boundary source (presence/realtime publication and some provider persistence seams) is unchanged. A passing local audit does not establish live-production behavior or absence of every possible future defect.

Artifact manifests record exact paths, SHA-256, clean-base/previous-patch application, byte/mode equality, reverse checks and preserved real Git state. Use the cumulative patch on the recorded main base, or the incremental patch after `2026-10-01-kb-template-download.patch`, never both.
