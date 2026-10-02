# Agent Completion Checklist — Vietmap as primary geocoder

- Task: `feat(geo): Vietmap as primary geocoder, with admin-editable keys` (commit `8343c833`)
- Scope: Geocoder provider chain reordered to **Vietmap → Google → Nominatim**; `VIETMAP_API_KEY` + `GOOGLE_MAPS_API_KEY` made admin-editable with `.env` seeding; prod `.env` populated and deployed.
- Files changed: 15 — `backend/app/services/geo/{providers,geocoding}.py`, `backend/app/services/integration_settings/providers/geo.py`, `backend/app/{core/config,schemas/integrations,models/geocode}.py`, `backend/scripts/prod-env.sh`, `backend/.env.example`, `backend/tests/{test_geocoding,test_integration_settings,test_runtime_surface_inventory}.py`, `docs/{architecture/system-architecture,ops/deployment-guide}.md`, `frontend/src/components/atomic-crm/integrations/{GeocoderSection.tsx,api.ts}`
- Instructions retrieved: `AGENTS.md`; `docs/ops/deployment-guide.md` (read in full, required before deploy); `standards/agent-completion-checklist.md`; `ak:cook` skill (`--auto`).
- Approval required: yes — plan approval, then explicit "commit push and deploy to prod".
- Approval evidence: plan approved via `ExitPlanMode`; user then wrote "once all done please commit push and deploy to prod"; chain order and prod-`.env` handling settled in the pre-plan questionnaire (`Vietmap → Google → Nominatim`; "I make the prod .env change and the deploy myself").

## Completion gates

| Gate | Status | Evidence (command and result, file reference, or N/A reason) |
|---|---|---|
| Requested behavior or artifact is complete | PASS | Chain is Vietmap → Google → Nominatim in `geocoding.py:311-346`. Live prod: `geocode("Núi Đèo, Hải Phòng")` → `(20.917090, 106.675100)`, `geocode_cache` row `('vietmap', …)`, second call cached. Both keys editable at `/admin/integrations/geocoder`. |
| Diff is limited to the approved scope | PASS | `git diff --stat HEAD~1 HEAD` = 15 files, +538/−95, all named in the plan. Two additions beyond the plan, both required by the deploy: `prod-env.sh` geocoder block (the generated prod template had no geocoder section at all) and the deployment-guide HEAD line (see docs gate). |
| Protected operations were avoided or approved | PASS | No migration authored (plan: `provider` is `String(32)`, already fits `vietmap`). Commit + push + deploy were explicitly authorized. Prod `.env` edited in place (backup kept, mode 0600 preserved); no `docker compose down`, no data-store force-recreate. |
| Focused tests/checks pass | PASS | `pytest tests/test_geocoding.py tests/test_integration_settings.py -q` → 74 passed. 13 new geocoding tests + 3 settings tests. |
| Broader regression tests pass when shared behavior changed | PASS | `pytest -q -m "not integration"` (the exact release-gate scope) → **3622 passed, 28 skipped, 323 deselected**, 0 failed, 6m24s. `tests/test_architecture_boundaries.py` + `test_runtime_surface_inventory.py` → 26 passed. |
| Lint passes for affected code | PASS | `ruff check .` (full repo) → "All checks passed!". `npx eslint` on both changed frontend files → exit 0. |
| Type checking passes for affected code | PASS | `npm run typecheck` (`tsc --noEmit --project tsconfig.app.json`) → clean, exit 0. |
| Build/import validation passes for affected code | PASS | `make release-check` → **exit 0**, all three lanes green, `release gate passed: golden_pass_rate_pct=100.0%`, frontend `npm run build` + `registry:check` (240 files) + `npm audit --omit=dev` all passed. Prod images built and booted (all containers healthy). |
| Security and privacy impact reviewed | PASS | Both keys are secrets: `GEO_SECRET_KEYS`, status-only via `admin_geocoder_view`, never returned by the API, masked in the UI, never logged. Values were piped to the host over stdin, never in argv, never printed; correctness proven by SHA-256 comparison (`0a017c81…`, `7eaca801…`) rather than by length. The key never enters the Plan, a tracked file, or shell history. |
| Performance and async-I/O impact reviewed | PASS | Non-blocking I/O throughout (`httpx.AsyncClient` via the shared registry). Nominatim's 1 s throttle deliberately left off the keyed hops. Cold Vietmap resolve = 2 sequential calls; bounded by `geocoder_timeout_seconds` and amortized to ~0 by the 30-day Redis + durable cache — confirmed by the cached second call. |
| Accessibility and Vietnamese UX reviewed for UI changes | PASS | Reused the existing `SecretField`/`SettingsGroup` pattern, so labelling, focus and `sr-only` legend semantics match the other settings panels. Vietnamese copy throughout, including the new group title "Geocoder Vietmap & Google Maps" and the order-explaining description; field hints say a blank value keeps the stored key. |
| Error handling and compatibility reviewed | PASS | Each hop is fail-open and returns `None` on any failure; `geocode()` keeps its never-raises contract (proved by `test_vietmap_error_falls_through_to_google_then_nominatim`). Unconfigured key ⇒ hop skipped entirely, so the chain still degrades to Nominatim-only. Cache prefix v3→v4 retires stale Google-first coordinates. New schema fields are optional in the PUT body, so old clients still work. |
| Documentation impact handled (includes `node scripts/check-doc-links.mjs` when agent routing changed) | PASS | `node scripts/check-doc-links.mjs` → "32 paths and 4 make targets across 4 documents all resolve". Updated `system-architecture.md` (three-hop chain, focus, two cache layers) and `deployment-guide.md` (env table + HEAD). **Also fixed a pre-existing release block**: the guide still named `0061_project_coordinates` as HEAD while `alembic heads` has been `0062_geocode_cache`, so `release-check` failed on `main` before this change. Verified the gate now passes. |
| No new unlinked `TODO`, `FIXME`, or `HACK` | PASS | `grep -nE "\b(TODO\|FIXME\|HACK)\b"` over all 15 changed files → no matches. |
| Final `git diff --check` passes | PASS | `git diff --check HEAD~1 HEAD` → clean, no whitespace errors. |
| Final `git status --short` reviewed | PASS | Clean after the pre-commit hook; `main…origin/main` in sync at `8343c833`. `git status --short` → empty. |

## Result

- Overall status: **PASS** — implemented, tested, committed, pushed, and deployed to production.
- Remaining risks or follow-ups:
  - **Vietmap quota.** Free tier is 60k transactions/month and each cold resolve costs 2. The 30-day cache keeps steady-state volume low, but a burst of distinct addresses burns 2 per address. `geocode_cache.provider` records which hop won, so the reordering can be measured.
  - **Vietmap's v4 routing engine is 503** (observed `route/v4`, `matrix/v4`, `tsp/v4`) while the geocode cluster is healthy. Out of scope here, but a blocker for any future routing work.
  - **Latency not measured in production.** A cold Vietmap resolve is two sequential calls. If a real turn feels slower, the fix is a dedicated shorter timeout for those two calls, not a chain reorder.
  - **Deferred, recorded not built:** search-as-you-type via the Autocomplete endpoint; a provider-tier metrics endpoint; and a Vietnamese landmark regression corpus built on the Núi Đèo class of failure.
  - **Pre-existing, out of scope:** GitHub reports 1 moderate Dependabot advisory on the default branch; below the release gate's threshold and not introduced here.
