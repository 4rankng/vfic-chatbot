# Agent Completion Checklist

Copied from `standards/agent-completion-checklist.md`. 16 gates, none dropped.

## Task record

- Task: Fix a wrong "1.5 km / 2 phút" distance the recruitment bot quoted for
  4P Electronics (KCN Tràng Duệ) from a candidate's address at 312 Nguyễn Công
  Hòa, An Biên, Hải Phòng. Verified against Google Maps: 13.6 km, 26 min.
- Scope: `backend/app/services/geo/` (geocoding + project-address resolution)
  and the poisoned rows in the production database
  (`projects`, `distance_estimate`).
- Files changed:
  - `backend/app/services/geo/geocoding.py`
  - `backend/app/services/geo/project_address.py`
  - `backend/tests/test_geocoding.py`
  - `backend/tests/test_project_address.py`
  - `backend/tests/integration/test_knowledge_ingestion.py` (test-double
    signature only)
- Instructions retrieved: `AGENTS.md`; `docs/development/code-standards.md`
  conventions applied from the existing module style. No other routed document
  applied.
- Approval required: production data change (explicitly requested: "fix prod db
  if store wrongly"). Deploy NOT performed — `AGENTS.md` requires approval and
  the deployment guide to be read first.
- Approval evidence: user instruction in-session, 2026-10-03
  ("check prod server and fix", "fix all issues you find, including wrong data in
  prod server").

## Completion gates

| Gate | Status | Evidence (command and result, file reference, or N/A reason) |
|---|---|---|
| Requested behavior or artifact is complete | PASS | Root cause proved, not guessed: `backend/app/services/geo/geocoding.py:349` walked the relaxation ladder to the bare city component and accepted Nominatim's `addresstype=city` centroid, because `_BLOCKED_ADDRESS_TYPES` only rejected street-level results. Reproduced live — `"Tầng 2, Công ty LG Electronics (LGE), KCN Tràng Duệ, An Phong, An Dương, Hải Phòng"` → `"TP. Hải Phòng"` → `20.8830967,106.6790381`. Fix: `_COARSE_PLACE_TYPES` + `precision="point"` refuses a relaxed hit on a populated-place/boundary centroid. |
| Diff is limited to the approved scope | PASS | `git status --short`: 5 files, all geo/ or their tests. The other 11 modified files are pre-existing user WIP on `get_project_distance` (`graph/*`, `test_graph_decisions.py`, the platform fixture) and were left untouched. |
| Protected operations were avoided or approved | PASS | No deploy, no commit, no push, no branch (not asked; `AGENTS.md` forbids by default). Prod writes were limited to NULLing 5 poisoned coordinate pairs and deleting 9 derived cache rows, after a `pg_dump` backup to `/opt/vfic/_geo_incident_backup/geo_20261003-034610.sql`. The unrelated `ss-prod-db` container (a different project, `silversea-prod`) was identified and NOT touched. |
| Focused tests/checks pass | PASS | `pytest tests/test_geocoding.py -q` → 39 passed. 5 new regression tests: city-centroid refusal, `area` keeps the ward, relaxed `industrial` still accepted, exact-text city still accepted, ward centroid refused by `point` but kept by `area`. |
| Broader regression tests pass when shared behavior changed | PASS | `pytest tests/test_geocoding.py tests/test_project_address.py tests/test_geo_distance.py tests/test_architecture_boundaries.py tests/test_graph_tools.py -q` → **153 passed**. `tests/integration/test_knowledge_ingestion.py`: 4 failures, proven pre-existing — verified identical on a stashed baseline (`4 failed, 15 passed` both with and without this change); they belong to the user's in-progress `get_project_distance` work, not this fix. |
| Lint passes for affected code | PASS | `ruff check app/services/geo/ tests/test_geocoding.py tests/test_project_address.py tests/integration/test_knowledge_ingestion.py` → `All checks passed!`. `ruff format --check` flags `distance.py`/`providers.py` which this change never touched — the baseline is not format-clean, so no reformat was applied (it would add unrelated churn); `--diff` confirms the drift is entirely in pre-existing lines. |
| Type checking passes for affected code | BLOCKED | `pyright` is configured (`backend/pyrightconfig.json`) but not installed in `.venv` (`.venv/bin/pyright: No such file or directory`). Not installed here rather than skipped silently. Signatures verified by import instead (below). |
| Build/import validation passes for affected code | PASS | `python -c "import app.services.geo.geocoding, app.services.geo.project_address"` → OK. `_CACHE_PREFIX` = `geo:geocode:v5:`, 19 coarse types, `geocode(query, *, viewbox=None, providers=None, precision='area')`. |
| Security and privacy impact reviewed | PASS | No new outbound endpoint, credential, or PII sink. `_resolve_providers` reads the already-encrypted `integration_settings` bundle through the existing service and never logs a key (it logs only a generic warning). Logging still avoids message content, per `AGENTS.md`. |
| Performance and async-I/O impact reviewed | PASS | No new I/O: the project path reuses the one geocode call and adds one credential read on an existing session. `_resolve_providers` is fail-open to the pre-existing keyless chain. The Nominatim ladder is unchanged in length. The empty-result branch removed a spurious `WARNING`+traceback per relaxed attempt — a log-volume win, not a cost. |
| Accessibility and Vietnamese UX reviewed for UI changes | N/A | No UI change. |
| Error handling and compatibility reviewed | PASS | Cache prefix bumped v4→v5 so Redis entries admitted under the old rule are retired. NOTE recorded: the durable `geocode_cache` table is keyed by raw `query` with no version, so the bump does NOT retire DB rows — prod rows were purged explicitly instead. `precision` defaults to `"area"`, so every existing caller (candidate-side `geocode_area`) is behaviourally unchanged. One pre-existing test that encoded the bug (`test_geocode_rejects_a_street_level_match` expecting a relaxed `city` hit) was kept and supplemented rather than deleted, and `test_refresh_from_kb_skips_a_resolved_project` was retargeted to the corrected "resolved = address AND coordinates" contract. |
| Documentation impact handled | PASS | `node scripts/check-doc-links.mjs` → `Agent routing OK: 32 paths and 4 make targets across 4 documents all resolve.` Module docstrings in `geocoding.py` and `project_address.py` updated with the incident and the `precision` contract. No routed doc points at the changed behaviour, so no doc edit was required. |
| No new unlinked `TODO`, `FIXME`, or `HACK` | PASS | `git diff backend/app/services/geo/ \| grep -E '^\+.*(TODO\|FIXME\|HACK)'` → none. |
| Final `git diff --check` passes | PASS | exit 0, no whitespace errors. |
| Final `git status --short` reviewed | PASS | Reviewed — 16 entries, 5 mine, 11 the user's WIP, none reverted. |

## Result

- Overall status: PASS with one BLOCKED gate (pyright not installed in the venv)
  and one open product decision (below).
- Remaining risks or follow-ups:
  1. **The code is not deployed.** Production still runs image `f6e48e6f`, which
     has neither the gate nor the credential wiring. Prod is safe only because
     the poisoned coordinates were removed — projects with no coordinates make
     the tool omit `distance_km` rather than invent one. Deploy needs approval
     (`make deploy`, after reading `docs/ops/deployment-guide.md`).
  2. **4P Electronics will still be wrong if the backfill is run as-is.**
     Measured against OSM ground truth for KCN Tràng Duệ
     (`20.8619428, 106.5619529`, `addresstype=industrial`): Vietmap resolves
     4P's stored address to `20.923086,106.559131` — **6.8 km off** — because the
     address legitimately begins "Tầng 2, Công ty LG Electronics (LGE)"
     (confirmed from the production brief; 4P occupies floor 2 of LG's building).
     The same address without that prefix resolves to within 1.1 km. The new
     gate does not catch this: it is a confident point, not a centroid.
     Recommended follow-up: a containment check — reverse-geocode the resolved
     point and require it to fall in the ward/district the address itself names.
     That would reject 4P (lands in Phường Hồng An, not An Dương) and keep
     LG-DISPLAY (lands in Phường An Phong, inside An Dương). Not built here: it
     is a new verification subsystem with ward-level granularity tradeoffs, i.e.
     a design decision, not a bug fix.
  3. **AMTRAN, EVA and Rorze are unverified.** No ground truth exists for KCN
     VSIP or KCN Nomura in OSM, and Vietmap gives two different answers for the
     same park depending on whether the company name is present ("Công ty
     AmTRAN, KCN Vsip, Thủy Nguyên" → `20.914783,106.697390`; "AMTRAN, KCN
     Vsip, Hải Phòng" → `20.904457,106.697352`). They currently have no
     coordinates, which is the safe state.
  4. Samsung SDS was verified correct against OSM and deliberately kept
     (`20.8267968,106.7744652` = KCN Đình Vũ).
