# Completion — geo-distance project matching ("dự án nào gần nhà?")

## Task record

- Task: implement the approved plan `local://project-geo-distance-plan.md` —
  extract each project's work address from its KB brief at ingest, geocode it
  with a free provider, and return `distance_km` per project from
  `list_active_projects` (nearest-first) so the agent answers "gần nhà" from
  data.
- Scope: one new service package (`app/services/geo/`), three `projects`
  columns + migration, two prompt/pipeline hooks, two non-pipeline hooks, one
  backfill script, the pure fit ranker, the catalog repository + tool, the tool
  schema + runtime rules, tests, one architecture-doc subsection.
- Files changed (mine only; `answer_repair.py`, `test_answer_completion_guard.py`,
  `test_graph_clients.py`, `test_lead_viewer_scope.py`,
  `docs/product/codebase-summary.md` were already modified in the working tree
  before this task and are untouched by it):
  - `backend/app/services/geo/__init__.py`, `geocoding.py`, `project_address.py` (new)
  - `backend/alembic/versions/0061_project_coordinates.py` (new)
  - `backend/scripts/backfill_project_coordinates.py` (new)
  - `backend/app/core/config.py`, `backend/.env.example`
  - `backend/app/models/company.py`
  - `backend/app/services/knowledge/prompts.py`, `pipeline.py`, `category_projections.py`
  - `backend/app/services/project/service.py`
  - `backend/app/services/retrieval/catalog_repository.py`
  - `backend/app/recruitment/domain/recommendation.py`
  - `backend/app/graph/tools/catalog.py`, `backend/app/graph/schemas.py`, `backend/app/graph/context.py`
  - `backend/app/graph/ports.py`, `backend/app/services/retrieval/repository.py`
  - `backend/tests/test_geocoding.py`, `test_project_address.py` (new)
  - `backend/tests/test_project_fit.py`, `test_graph_tools.py`, `test_persona.py`,
    `test_project_catalog_features.py`, `test_runtime_surface_inventory.py`,
    `tests/integration/test_knowledge_ingestion.py`
  - `docs/architecture/system-architecture.md` (§10 tools bullet)
- Instructions retrieved: `AGENTS.md` + `.claude/CLAUDE.md` (repo constitution),
  `standards/agent-completion-checklist.md`, `docs/architecture/system-architecture.md`.
- Approval required: none beyond the approved plan. No protected-path file was
  touched (no auth/webhook/ratelimit/core-runtime file).
- Approval evidence: user message "Plan approved." with the plan inlined.

## Deviations from the approved plan (all four required to satisfy its acceptance criteria)

1. **Query relaxation ladder** in `geocode` (`_query_variants`,
   `_MAX_QUERY_ATTEMPTS = 5`). Evidence: the plan's verification step 3 requires
   non-null coordinates for the 4P brief's address, but Nominatim's free-form
   search returns `[]` for
   `Tầng 2, Công ty LG Electronics (LGE), KCN Tràng Duệ, An Phong, An Dương, Hải Phòng`
   and for `KCN Tràng Duệ, An Dương, Hải Phòng` — it rejects the whole query when
   any comma-separated component is not a place it knows. Retrying the caller's
   own suffixes resolves it. Same single `client.get` call site, so the
   runtime-surface inventory is unchanged.
2. **Street-match gate** (`_BLOCKED_ADDRESS_TYPES`). Evidence: the ladder's
   first hit for that address was `addresstype=road` —
   `Đường Huyện 19, An Tĩnh, Phường Việt Hòa, Thành phố Hải Dương` (35 km from the
   industrial park), i.e. a confident wrong origin. Hits whose `addresstype` is a
   street/exact-address class are now rejected and the walk continues to a real
   place (or to a miss).
3. Cache prefix bumped `geo:geocode:v1:` → `v2:` because 1 and 2 changed what a
   stored value means; a bump retires entries written under the previous rules
   instead of serving them for their full TTL.
4. **The geocoder is reached through the retrieval port, not a direct import.**
   The plan said to import `app.services.geo.geocoding.geocode` into
   `app/graph/tools/catalog.py` (citing `graph/adapters.py` as precedent), but
   `tests/test_graph_import_guard.py::test_graph_runtime_modules_have_no_concrete_imports`
   forbids any `app.services`/`app.models` import in a graph runtime module —
   including one nested in a function — except in the three composition modules
   (`adapters.py`, `client_cache.py`, `factories.py`). The seam is therefore
   `GraphRetrievalPort.geocode_area`, declared in `app/graph/ports.py` and
   implemented on `RetrievalRepository` (the facade the graph injects), which
   delegates to the same cached/throttled/fail-open client. The plan's
   test instruction (monkeypatch `app.graph.tools.catalog.geocode`) is replaced
   by a `geocode_area` method on the fake port; every location-passing test
   installs it explicitly.

## Completion gates

| Gate | Status | Evidence (command and result, file reference, or N/A reason) |
|---|---|---|
| Requested behavior or artifact is complete | PASS | Address extraction + grounding + geocoding at ingest; `distance_km` per row with nearest-first default order; agent guidance in `schemas.py` + `context.py`; backfill script. |
| Diff is limited to the approved scope | PASS | `git status --short` — only the files listed above (the five pre-existing modifications are untouched). |
| Protected operations were avoided or approved | PASS | One additive, reversible migration (no data change); no auth/webhook/ratelimit/core-runtime edit; no dependency change. |
| Focused tests/checks pass | PASS | `pytest -q -p no:randomly tests/test_geocoding.py tests/test_project_address.py tests/test_project_fit.py tests/test_graph_tools.py tests/test_persona.py tests/test_runtime_surface_inventory.py tests/test_architecture_boundaries.py tests/test_recruitment_domain_imports.py tests/test_knowledge_pipeline.py tests/test_project_service.py tests/test_category_projections_sibling_batch.py tests/test_project_catalog_features.py tests/test_graph_import_guard.py` → 222 passed. |
| Broader regression tests pass when shared behavior changed | PASS | `pytest -q -p no:randomly tests --ignore=tests/integration` → **3598 passed, 28 skipped** (0 failed). |
| Lint passes for affected code | PASS | `ruff check` on every changed/added Python file → "All checks passed!". (`ruff format --check` is not a repo gate: untouched files such as `app/graph/context.py` also fail it.) |
| Type checking passes for affected code | N/A | No mypy/pyright gate in this repo (`pyproject.toml` ships ruff only; `backend/Makefile` has no type target). |
| Build/import validation passes for affected code | PASS | `.venv/bin/python -c "import app.main, app.workers.ingest_worker"` → OK (after fixing the `app.services.project` re-export import cycle). |
| Security and privacy impact reviewed | PASS | Geocoder queries are project work addresses and the candidate's stated area — no candidate PII, no lead/message data. The new egress is the only new reviewed provider row. `GEOCODER_BASE_URL` is operator-settable; the client sends no credentials. |
| Performance and async-I/O impact reviewed | PASS | One throttled provider call per distinct query, 30-day positive / 6-hour negative Redis cache, single process-scoped httpx client, no DB change on the read path (`latitude`/`longitude` ride the existing catalog `select`). Worst cold case is a 5-attempt ladder at the provider's 1 req/s floor; ingest is background, and the tool path normally resolves in one attempt. |
| Accessibility and Vietnamese UX reviewed for UI changes | N/A | No UI change. Vietnamese copy added: the tool description, rule (8) of the presentation contract, the runtime rule, and the address-extraction prompt. |
| Error handling and compatibility reviewed | PASS | Every new path is fail-open: `geocode` never raises; `refresh_from_kb`/`refresh_from_address` swallow their own failures; the tool catches a geocode failure. A project without coordinates keeps the previous payload exactly (proved below). |
| Documentation impact handled | PASS | §10 of `docs/architecture/system-architecture.md` documents the flow, the provider, the cache, and the fail-open contract. `node scripts/check-doc-links.mjs` → "Agent routing OK: 32 paths and 4 make targets across 4 documents all resolve." |
| No new unlinked `TODO`, `FIXME`, or `HACK` | PASS | `grep -n "TODO\|FIXME\|HACK"` over the changed files → none added. |
| Final `git diff --check` passes | PASS | `git diff --check` → no whitespace errors. |
| Final `git status --short` reviewed | PASS | 23 modified + 5 untracked, all accounted for above. |

## Verification evidence

1. Focused suites: 204 passed (command above).
2. Migration round-trip on the dev Postgres (port 5443):
   `alembic upgrade head` → `downgrade -1` → `upgrade head` → `alembic current`
   → `0061_project_coordinates (head)`.
3. Extraction + geocoding with the real LLM and the real geocoder:
   `.venv/bin/python scripts/backfill_project_coordinates.py --re-extract` →
   `updated=5 skipped=4 failed=0`. `projects` rows:
   - 4P `Tầng 2, Công ty LG Electronics, KCN Tràng Duệ, Huyện An Dương (xã An Phong), TP. Hải Phòng` → (20.8830967, 106.6790381)
   - Amtran VSIP `Khu công nghiệp VSIP Thủy Nguyên, TP. Hải Phòng` → (20.8830967, 106.6790381)
   - Samsung SDS Đình Vũ (×3) `Công ty Cổ phần Liên hợp Kho bãi UWG, Khu công nghiệp Đình Vũ, TP. Hải Phòng` → (20.8267968, 106.7744652)
   The 4 skipped projects' briefs genuinely carry no work address (short FAQ /
   bus-timetable files: `LG Display Hải Phòng`, `LG Display Bắc Ninh`,
   `Samsung Bắc Ninh`, `Foxconn Nghệ An`), so `skipped` is correct behavior.
4. New-behavior proof (throwaway script, run then deleted): with a fake port of
   two coordinate-bearing projects whose `geocode_area` → `(20.86, 106.68)`,
   `list_active_projects(location="An Dương")` returns `["kcn-trang-due",
   "kcn-nomura"]` with `distance_km [0.0, 6.1]` and the note
   `địa điểm Hải Phòng, An Dương · khớp · cách 0.0 km`. A port returning `None`
   yields the pre-change order with no `distance_km` key at all.
   The same behavior is pinned permanently in `tests/test_graph_tools.py`
   (`test_list_active_projects_reports_distance_nearest_first`,
   `..._without_geocoded_origin_keeps_the_previous_output`,
   `..._without_location_never_geocodes`) and in `tests/test_project_fit.py`.
5. Fail-open proof: `GEOCODER_BASE_URL=http://127.0.0.1:9/` (nothing listening)
   with the real `geocode` behind the port → `geocode()` returns `None`, the
   catalog still returns `status="matched"`, `total=2`, no `distance_km`, no
   exception.
6. Runtime-surface inventory: the new provider-transport file adds exactly one
   broad-scan row
   `{"category": "provider_boundary", "file": "app/services/geo/geocoding.py", "scope": "geocode", "call": "get", "count": 1}`;
   `EXPECTED_BROAD_BOUNDARY_COUNTS["provider_boundary"]` 91 → 92 and
   `EXPECTED_BROAD_BOUNDARY_SHA256` recomputed to
   `f74ea30c98e08c0208da2d6aebefaf312933b9c49c26ab147fe70f933533f5f3` (re-verified
   unchanged after the ladder/gate refactor). The non-broad fixture is unchanged.
7. Ingest hook proof (integration lane, real Postgres):
   `pytest tests/integration/test_knowledge_ingestion.py -k "work_address or coordinates_null"`
   → 2 passed — a brief with `Địa chỉ làm việc` stores address + coordinates; a
   brief without one stores nothing and never calls the geocoder.

## Result

- Overall status: PASS (all gates PASS or N/A).
- Remaining risks or follow-ups:
  1. **Geocoding precision.** Public Nominatim has thin Vietnamese coverage: for
     the 4P address the gate rejects the street fuzzy-match and the ladder
     therefore lands on the Hải Phòng city centroid (~12 km from KCN Tràng Duệ),
     which makes two Hải Phòng projects tie on distance. `distance_km` is
     documented as an approximate ~10 km-scale figure. A self-hosted Nominatim
     with better VN OSM data — or any other Nominatim-compatible endpoint — is a
     `GEOCODER_BASE_URL` change with no code change.
  2. **Negative cache on provider throttling.** A 429/timeout is cached as a
     6-hour miss (approved plan behavior). A burst that trips Nominatim's policy
     therefore poisons that query for 6 hours; the 1 req/s client throttle is the
     mitigation. Worth revisiting if a real deployment sees 429s.
  3. **Cold-cache latency on the chat path.** A long candidate area can walk up
     to 5 throttled attempts (~4 s) before the first cached answer. Typical areas
     ("An Dương", "Hải Phòng") resolve on the first attempt.
  4. `ProjectRepository.get_latest_document_with_text` orders by
     `created_at DESC` with no tiebreaker, so two upload documents created in one
     transaction have no deterministic "latest". Pre-existing (feature extraction
     reads it too); the integration test pins `created_at` explicitly rather than
     relying on the tie.

## Broader lane

`pytest -q -p no:randomly tests --ignore=tests/integration` →
**3598 passed, 28 skipped, 2 warnings in 400s**. The first run of this lane
caught two regressions the focused list had missed — the graph import guard
(deviation 4) and nine `test_project_catalog_features.py` fakes that lacked the
two new select columns — both fixed and re-verified green here.

Integration lane: `pytest tests/integration/test_knowledge_ingestion.py -k "work_address or coordinates_null"`
→ 2 passed (real Postgres, fake LLM + fake geocoder).
