# Agent Completion Checklist

Copied from `standards/agent-completion-checklist.md`. 16 gates, none dropped.

## Task record

- Task: Make every stored project coordinate justifiable — a human-verified
  gazetteer row, or a provider point whose reverse geocode reports a place the
  address itself names — and drop the keyless provider that produced the wrong
  "1.5 km / 2 phút" distance for 4P Electronics (KCN Tràng Duệ) from a
  candidate at 312 Nguyễn Công Hòa, An Biên, Hải Phòng (Google Maps: 13.6 km /
  26 min).
- Scope: `backend/app/services/geo/` (chain, containment check, resolver),
  the geocoder settings surface, `backend/scripts/seed_geo_gazetteer.py`, the
  routed docs, and the poisoned production rows (`projects`,
  `geocode_cache`, `geocode_place_check`, `distance_estimate`).
- Files changed (commits `2a700eac`, `267d24c4`, `651ea352`):
  - `backend/app/services/geo/providers.py` — `google_reverse` splits Google's
    composite `formatted_address` per comma segment; `nominatim_reverse` and
    `_NOMINATIM_CLIENT` deleted; `_COARSE_PLACE_TYPES` + `require_point` added
    to `google_geocode`; `GeocodeHop.rejects_coarse`.
  - `backend/app/services/geo/verification.py` — Google-only reverse lookup;
    `_RULES_VERSION` v6→v7.
  - `backend/app/services/geo/geocoding.py` — relaxation ladder, throttle,
    `_query_variants`, `_BLOCKED_ADDRESS_TYPES`, `_COARSE_PLACE_TYPES` and the
    Nominatim client deleted; `_CACHE_PREFIX`/`_DB_KEY_VERSION` v6→v7; `geocode`
    passes `require_point` to hops that can refuse a coarse answer.
  - `backend/app/services/geo/factory_point.py` — keyless ladder removed as a
    candidate source (Google + Vietmap only).
  - `backend/app/core/config.py`, `backend/.env.example`,
    `backend/scripts/prod-env.sh` — `GEOCODER_BASE_URL`,
    `GEOCODER_USER_AGENT`, `GEOCODER_MIN_INTERVAL_SECONDS` removed.
  - `backend/app/models/geocode.py`,
    `backend/app/services/retrieval/{repository,catalog_repository}.py`,
    `backend/app/services/integration_settings/providers/geo.py`,
    `backend/app/services/geo/project_address.py` — prose and provider lists.
  - `backend/tests/test_geocoding.py` (rewritten for the two-hop chain),
    `backend/tests/test_geo_verification.py`,
    `backend/tests/test_runtime_surface_inventory.py`,
    `backend/tests/integration/test_knowledge_ingestion.py`,
    `backend/tests/helpers/http_fake.py` (request-routed fakes).
  - `backend/scripts/backfill_project_coordinates.py` — applies the
    credential-log guard its own entrypoint bypassed.
  - `docs/ops/deployment-guide.md`, `docs/architecture/system-architecture.md`.
- Instructions retrieved: `AGENTS.md`; `docs/ops/deployment-guide.md` (read in
  full before deploying); `standards/agent-completion-checklist.md`;
  `backend/tests/test_architecture_boundaries.py` (unchanged by this work).
- Approval required: production deploy + production data writes.
- Approval evidence: user instruction in-session, 2026-10-03 — "fix all issues
  you encounter then commit, push and deploy to prod (no need run release-check)"
  — following the earlier "check prod server and fix … including wrong data in
  prod server". The in-flight scope change ("focus on vietmap and google only,
  no need to care Nominatim") was resolved with the user picking **"Remove
  Nominatim from the chain entirely"**.

## Completion gates

| Gate | Status | Evidence (command and result, file reference, or N/A reason) |
|---|---|---|
| Requested behavior or artifact is complete | PASS | Defect proved, not guessed: with Google's `formatted_address` stored whole, `place_matches({norm("Đại Bản, Hồng An, Hải Phòng, Việt Nam")}, "an phong")` returned `True` — the containment check accepted both the 6.81 km Vietmap error and the original city centroid. Proved by reverting only the split and re-running: `3 failed, 33 passed` (`test_google_reverse_splits_the_formatted_address`, `test_end_to_end_the_vietmap_error_is_rejected` → `FactoryPoint(point=(20.923086, 106.559131) … matched_anchor='an phong')`, `test_end_to_end_the_city_centroid_is_rejected_by_the_google_source` → the centroid accepted). With the fix: `36 passed`. Nominatim removed per the user's choice: `KEYED_GEO_HOPS == (google, vietmap)`, no keyless hop, `geocoding.py` imports no HTTP client. |
| Diff is limited to the approved scope | PASS | `git show --stat 2a700eac 267d24c4 651ea352` — geo chain, its settings/env/docs, its tests, plus the one log-guard fix. `12ca429b fix(graph): gate the password flow on a Jev login-problem judgment` is a **concurrent session's** work on the same checkout (their files: `graph/decisions.py`, `graph/context.py`, `graph/router.py`, `tests/test_graph_decisions.py`, `tests/test_graph_runner_turn.py`); it was already committed and pushed when this task's tree was inspected, and it is not described as this task's work. |
| Protected operations were avoided or approved | PASS | Deploy + prod writes explicitly requested. Every write followed a fresh `pg_dump`: `vfic_pg_backup_2026-10-03_133006.dump` (65 MB, 13:30) taken by `make deploy` before `alembic upgrade head`; a second backup preceded the fast-track backend deploy. Blue/green cutover with a passing smoke gate (`SMOKE OK [single-message] outcome='sent'`, `[progressive-send]`, `[support-oa-hotline]`, `[support-oa-clarify]`); no rollback was needed. The unrelated `ss-prod-db` container (a different project) was never touched. |
| Focused tests/checks pass | PASS | `pytest -q tests/test_geo_verification.py tests/test_geocoding.py tests/test_project_address.py tests/test_geo_distance.py tests/test_graph_tools.py tests/test_architecture_boundaries.py tests/test_runtime_surface_inventory.py` → **183 passed**. Integration contract: `pytest -m integration tests/integration/test_knowledge_ingestion.py::test_build_project_index_extracts_and_geocodes_the_work_address …::test_build_project_index_leaves_coordinates_null_without_a_work_address` → **2 passed** (retargeted from the removed `project_address.geocode` to `resolve_factory_point`). |
| Broader regression tests pass when shared behavior changed | PASS | Full unit suite: `pytest -q -m "not integration"` → `1 failed, 3705 passed, 28 skipped, 323 deselected`. The one failure, `tests/test_direct_turns.py::test_typing_bridge_never_falls_back_to_stale_environment_token` (`assert 2 >= 3`), is a 65 ms-window timing assertion: it passes in isolation (`14 passed in 5.28s`) and is unrelated to geo. `tests/integration/test_knowledge_ingestion.py` → `4 failed, 15 passed`, the pre-existing per-criterion extraction drift against stale single-call fakes (`extract_product_features`) that this plan documented; none of the 4 touches the geo path. |
| Lint passes for affected code | PASS | `.venv/bin/ruff check app tests scripts` → `All checks passed!`. `ruff format --check` flags files this change never touched (`distance.py`, `geocoding.py` pre-existing lines); the baseline is not format-clean, so no reformat was applied. |
| Type checking passes for affected code | PASS | `uvx pyright app/graph` → `0 errors, 0 warnings, 0 informations` (the same lane `release-check` runs). |
| Build/import validation passes for affected code | PASS | `python -c "import app.services.geo.{geocoding,providers,verification,factory_point}"` → OK; `_CACHE_PREFIX == "geo:geocode:v7:"`, `_DB_KEY_VERSION == "v7:"`, `verification._RULES_VERSION == "v7"`, `KEYED_GEO_HOPS` names `['google','vietmap']` with `rejects_coarse == [True, False]`. Both images built and pushed for the deploy (AMD64). |
| Security and privacy impact reviewed | PASS | One real issue found and fixed: `scripts/backfill_project_coordinates.py` used `logging.basicConfig` without `silence_credential_bearing_transport_loggers()`, so httpx's INFO records printed the full geocoder URL — API key included — during the production run (`651ea352`; verified `logging.getLogger("httpx").level == 30` after the call). No new outbound endpoint or credential sink; the containment check logs place names and provider ids only, never message content. **Follow-up for a human:** the Google and Vietmap keys appeared in plaintext in an operator-visible stream and should be rotated. |
| Performance and async-I/O impact reviewed | PASS | Fewer calls, not more: the removed ladder could spend up to 5 throttled (1 req/s) Nominatim attempts per cold address, plus one reverse call per distinct candidate; the chain is now at most one forward call per configured hop and one Google reverse per distinct candidate, all cached (Redis 30 d / 6 h negative, durable `geocode_cache` + `geocode_place_check`). The gazetteer answers 5 of the 6 live projects with **zero** API calls. The prod backfill of 6 projects took 18 s wall (`updated=6 skipped=0 failed=0`). |
| Accessibility and Vietnamese UX reviewed for UI changes | N/A | No UI change. The user-visible behavior is the reply text: the tool omits `distance_km` (and answers "chưa xác định được vị trí") instead of quoting an unjustified number. |
| Error handling and compatibility reviewed | PASS | Fail-open preserved: every hop and every reverse lookup returns `None`/miss on outage, non-200, malformed payload, or a refused coarse answer; nothing raises. Cache versions bumped on both tiers (Redis `geo:geocode:v6:`→`v7:`, durable `geocode_cache` `v6:`→`v7:`, `geocode_place_check.coord_key` `v6:`→`v7:`) so answers produced by the removed chain retire with no migration. `precision` is retained and now means "Google must not answer with a populated place or administrative boundary"; Vietmap's payload exposes no equivalent flag, which is documented rather than assumed. Removing the keyless hop is a deliberate compatibility break: an installation with no key now reports no distance — recorded in `.env.example`, `prod-env.sh` and the deployment guide. |
| Documentation impact handled (includes `node scripts/check-doc-links.mjs` when agent routing changed) | PASS | `node scripts/check-doc-links.mjs` → `Agent routing OK: 32 paths and 4 make targets across 4 documents all resolve.` `docs/ops/deployment-guide.md` §4 (Alembic HEAD `0065_geo_gazetteer`, both new tables, the seeding step), §6 (two-hop geocoder, `v7` key versions, the removed settings) and `docs/architecture/system-architecture.md` §10 updated. |
| No new unlinked `TODO`, `FIXME`, or `HACK` | PASS | `git show 2a700eac 267d24c4 651ea352 \| grep -E '^\+.*(TODO\|FIXME\|HACK)'` → none. |
| Final `git diff --check` passes | PASS | exit 0 on each commit. |
| Final `git status --short` reviewed | PASS | Clean at `651ea352` before the fast-track backend deploy; `origin/main` == `651ea352`. |

## Result

- Overall status: PASS. Deployed and verified in production.
- **Production proof (Step 8e, read-only probe in the active colour):** every
  non-NULL project's coordinate reverse-geocodes to a place its own address
  names —
  `4P Electronics 20.86194,106.56195 anchors=['trang due','an phong','an duong'] matched=['trang due','an phong']`,
  `AMTRAN/EVA 20.90957,106.72318 matched=['vsip','thuy nguyen']`,
  `LG-DISPLAY 20.86194,106.56195 matched=['trang due']`,
  `Rorze 20.90065,106.59174 matched=['hong an']`,
  `Samsung SDS 20.82680,106.77447 matched=['dinh vu']`. 4P is nowhere near
  Đại Bản/Hồng An.
- **Production proof (Step 8f, the original complaint):** from
  `312 Nguyễn Công Hòa, An Biên, Hải Phòng` (origin resolves to
  `20.8454332,106.6690782` via Google, `precision="point"`), 4P Electronics
  measures **16.7 km / 26 min** — against the old "1.5 km / 2 phút" and Google
  Maps' 13.6 km / 26 min. The travel time matches exactly; the distance differs
  by 3 km because the road estimate comes from Vietmap's Matrix while Google
  Maps' UI uses its own routing (different road snapping, same route). Every
  other project is now 12.2–16.7 km / 19–26 min instead of absent.
- **Production data repair:** gazetteer seeded (`gazetteer: 3 written, 0 already
  correct`); backfill `updated=6 skipped=0 failed=0`; `geocode_cache` 9→2,
  `geocode_place_check` (non-`v7:`) purged, `distance_estimate` 3 rows deleted
  (the poisoned pair among them). Remaining rows are `v7:` only, and the stored
  reverse names are split per place (`v7:20.90065,106.59174 → … | hong an |
  hai phong | viet nam`) rather than one composite string.
- **Deploy:** `make deploy` → `bg_deploy done. active=web-blue tag=267d24c4`,
  smoke gate passed, `PIPELINE OK: consumers live, no conversation awaiting a
  reply, outbox drained`, public `/health` → `{"status":"ok","env":"production"}`,
  prod alembic at `0065_geo_gazetteer`. A fast-track `make deploy-backend`
  followed for `651ea352`.
- Remaining risks or follow-ups:
  1. **Rotate the Google and Vietmap API keys** — they were printed in plaintext
     by the pre-fix backfill script (`651ea352` stops the leak; the exposure
     already happened).
  2. **KCN VSIP's gazetteer row sits at the park's eastern end**
     (20.9095671,106.7231804) because a plant's position inside a multi-km park
     is not knowable from the address. If a recruiter supplies a plant pin, add
     it as a more specific row; `gazetteer.lookup` prefers the most specific
     component, so it will win over the park row.
  3. **`geo_gazetteer.is_active` is not consulted by `lookup`** — a deactivated
     row would still answer. Harmless today (nothing sets it false; the plan
     explicitly said not to rewrite the lookup), but it is a latent trap worth a
     one-line filter when someone next touches that module.
  4. **The 4 pre-existing failures in
     `tests/integration/test_knowledge_ingestion.py`** (per-criterion extraction
     contract drift in `pipeline.extract_product_features` against stale
     single-call fakes) are unrelated to this work and still open.
  5. **`make release-check` was waived** by explicit user instruction; the gates
     it would have run were executed individually instead (pyright on
     `app/graph`, `ruff check`, the unit suite, `check-doc-links.mjs`, the two
     migration-roundtrip tests are the one lane not run).
