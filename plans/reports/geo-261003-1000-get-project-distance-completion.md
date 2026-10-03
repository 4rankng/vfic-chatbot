# Agent Completion Checklist — get_project_distance (address → plant distance)

- Task: `fix(geo): answer spoken project names and clear the release gate` (`e7874160`), on top of `05b8e28c feat(graph): add get_project_distance tool`
- Scope: Make the agent able to answer *"312 Nguyễn Công Hòa tới AmTRAN bao xa"* — a new distance tool, a prompt rule for that question shape, a fallback for spoken names that miss the catalog, and the answer-cache guard.
- Files changed (this task): `backend/app/graph/tools/catalog.py`, `backend/app/graph/tools/__init__.py`, `backend/app/models/__init__.py`, `backend/tests/test_graph_tools.py`
- Files changed (prior task, same feature): `backend/app/graph/schemas.py`, `backend/app/graph/context.py`, `backend/app/graph/answer_cache.py`
- Instructions retrieved: `AGENTS.md`; `docs/ops/deployment-guide.md` (read in full); `ak:agentkit` (routed to `ak:cook` — single obvious domain, implementation).
- Approval required: yes — operator directed "commit all code", then "complete all tasks and deploy to prod", then waived `make release-check` explicitly.
- Approval evidence: questionnaire settled the geocoder order; operator waived the release gate with "dont need to run make release-check" after the equivalent checks had been run manually.

## Diagnosis (the actual defect)

The Vietmap geocoder was never the problem. Evidence gathered on the box:

| Check | Result |
|---|---|
| AMTRAN project | active, coordinates `(20.914119, 106.680492)` |
| Active projects with coordinates | 6 of 6 |
| `geocode("312 Nguyen Cong Hoa")` | `(20.845682, 106.668870)` — correct |
| `geocode_cache` rows for the candidate's address | **none** |

A geocode miss would have written a NULL-coordinate miss row. There was no row at
all, so `RetrievalRepository.geocode_area` was never called: the model never
passed `location`. The `location` parameter was documented only as *"khi ứng viên
hỏi dự án gần nhà"* and the agent prompt only carried a *"HỎI DỰ ÁN GẦN NHÀ"*
rule. Nothing told the model that *"312 Nguyễn Công Hòa tới AmTRAN bao xa"*
should route an address into a distance lookup.

## Completion gates

| Gate | Status | Evidence (command and result, file reference, or N/A reason) |
|---|---|---|
| Requested behavior or artifact is complete | PASS | Prod, `get_project_distance`: user wording → `company_unmatched` with the nearest-first list (AMTRAN 9.2 km / 12 min); `company="Amtran"` → `measured`, AMTRAN 9.2 km; no company → 6 projects ranked. All three verified on the live container at tag `e7874160`. |
| Diff is limited to the approved scope | PASS | 4 files this task, 3 the prior. One deviation, disclosed: the `__all__` fix in `app/models/__init__.py` belongs to another agent's `DistanceEstimate` commit and was required to make the lint lane green. |
| Protected operations were avoided or approved | PASS | No migration authored. Commit/push/deploy explicitly authorized. No `docker compose down`, no data-store force-recreate; rollback state preserved (`PREV=blue@cc2d2a71`). |
| Focused tests/checks pass | PASS | `pytest tests/test_graph_tools.py tests/test_geo_distance.py tests/test_geocoding.py tests/test_architecture_boundaries.py tests/test_runtime_surface_inventory.py` → **126 passed**. 5 distance tests including the new `company_unmatched` and `unresolved_location` cases. |
| Broader regression tests pass when shared behavior changed | PASS | Full release-gate backend scope `pytest -m "not integration"` → **3622 passed, 28 skipped**, 0 failed (run on the immediately preceding commit; this task's delta is 4 files, all covered by the 126 above). |
| Lint passes for affected code | PASS | `ruff check app/` → "All checks passed!". |
| Type checking passes for affected code | PASS | `uvx pyright app/graph` → **0 errors, 0 warnings** (was 3 errors before the `rows` shadowing and `float \| None` fixes). |
| Build/import validation passes for affected code | PASS | Both images built and pushed; `TOOLS_REGISTRY` and `TOOL_SCHEMAS` both hold 12 tools with an empty symmetric difference. |
| Security and privacy impact reviewed | PASS | The reply is candidate-specific, so `get_project_distance` is deliberately **excluded** from `_PROJECT_DATA_TOOLS`: the exact cache tier keys on a question hash, but the semantic tier keys on the embedding, which could otherwise hand one candidate's kilometres to another. Documented in the allowlist so a future reader does not "fix" it by adding the tool. |
| Performance and async-I/O impact reviewed | PASS | Reuses the existing throttled, two-layer-cached geocoder; no new network path. Company matching reuses `rank_projects` rather than re-implementing alias matching. The fallback costs one extra in-process rank, not a network call. |
| Accessibility and Vietnamese UX reviewed for UI changes | PASS | No UI change in this task. Prompt rule and all four `safe_reply` strings are Vietnamese and tell the recruiter the concrete next action (ask for a fuller address, or pick the right plant) rather than failing vaguely. |
| Error handling and compatibility reviewed | PASS | Four distinct, honest statuses: `missing_location`, `unresolved_location`, `unknown_project`, `company_unmatched`, plus `unmeasured_project`. `geocode()` still never raises — an empty Nominatim array surfaces as a logged `IndexError` and degrades to the "ask for a better address" reply. |
| Documentation impact handled | PASS | `node scripts/check-doc-links.mjs` → "32 paths and 4 make targets across 4 documents all resolve" (run for the geocoder task; the distance tool added no new routed document). |
| No new unlinked `TODO`, `FIXME`, or `HACK` | PASS | None in the changed files. |
| Final `git diff --check` passes | PASS | No whitespace errors; commit `e7874160` created without incident. |
| Final `git status --short` reviewed | PASS | Clean after commit; `main…origin/main` in sync at `e7874160`. |

## Result

- Overall status: **PASS** — implemented, tested, committed (`e7874160`), pushed, deployed to production, and verified live.
- Release gate: **operator-waived**. `make release-check` was stopped on instruction. The gates it would have run were covered manually: `pyright app/graph` 0 errors, `ruff check app/` clean, 126 tests passing across the affected suites, and the full backend scope had passed 3622/3622 on the parent commit.
- Deployment: `bg_deploy done. active=web-green tag=e7874160`; smoke gate and turn-pipeline gate both passed before the flip; frontend image `e7874160` recreated. Edge `https://bot.tingting.vip/health` → `{"status":"ok","env":"production"}`. All containers healthy (4 × `worker-chatbot`, `web-green`, `frontend`). Rollback available at `blue@cc2d2a71` without a rebuild.
- Remaining risks or follow-ups:
  - **The agent's routing is prompt-level, not enforced.** The new rule makes the model call `get_project_distance` for this shape, but nothing hard-fails a turn that forgets. A deterministic backstop (infer `location` from the stated area when the question names an address) is a separate change.
  - **`list_active_projects(location=…)` still shares distance across candidates.** It remains in `_PROJECT_DATA_TOOLS`, and the pre-turn cacheability gate cannot see tool *arguments*, so a location-bearing turn could still be stored. The new tool's exclusion closes the path this feature introduces; closing the older one needs argument plumbing into the cache decision.
  - **Straight-line vs road distance.** Verified numbers are the provider's road estimates with `duration_min`; the straight-line figure is only the fallback when no estimate exists.
  - **Vietmap quota** — free tier 60k transactions/month, 2 per cold resolve; the 30-day Redis + `geocode_cache` layers keep steady state low.
  - **Vietmap's v4 routing engine returns 503** (`route/v4`, `matrix/v4`, `tsp/v4`) while the geocode and distance-estimate clusters answer 200. Worth watching now that road estimates depend on it.
  - **Not verified:** I did not exercise a live candidate conversation end-to-end (that would send real messages to real people). Verification was at the tool boundary inside the live container.
