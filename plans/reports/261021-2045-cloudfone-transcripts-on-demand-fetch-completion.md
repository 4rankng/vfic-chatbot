# Agent Completion Checklist

Copy this file to
`plans/reports/<YYMMDD-HHmm>-<slug>-completion.md` for each implementation task.
Replace every `PENDING` with `PASS`, `N/A`, or `BLOCKED`. A task is not complete
while any item is `PENDING` or `BLOCKED`.

## Task record

- Task: The Cloudfone transcripts viewer showed an empty table for any day the daily pass had not covered. The viewer must now fetch that day from Cloudfone on demand — unless the database already says the day holds no record.
- Scope: per-day inspected-day marker (migration 0077 + model), shared day fetch/transcribe/store routine, on-demand day fetch endpoint, the viewer's automatic fetch and its states, tests, deployment-guide Alembic HEAD.
- Files changed: backend/alembic/versions/0077_cloudfone_transcript_days.py (new), backend/app/models/cloudfone.py, backend/app/services/cloudfone_transcripts.py, backend/app/services/cloudfone.py, backend/app/schemas/integrations.py, backend/app/api/integrations.py, backend/tests/test_cloudfone_transcript_backfill.py (new), backend/tests/test_cloudfone_transcripts_api.py, backend/tests/integration/test_cloudfone_transcript_store.py, backend/tests/integration/conftest.py, backend/tests/test_runtime_surface_inventory.py, frontend/src/components/atomic-crm/integrations/api.ts, frontend/src/components/atomic-crm/integrations/CloudfoneTranscriptsSection.tsx, frontend/src/components/atomic-crm/integrations/CloudfoneTranscriptsSection.test.tsx, docs/ops/deployment-guide.md (Alembic HEAD line), plans/qa-261021/ (verification artifacts)
- Instructions retrieved: session message ("when admin open and that day is empty, you need to fetch from cloudfone, unless, db mention that day has no record then dont need to fetch"); repo AGENTS.md (scoped workflow, boundary rules, completion record), docs/ops/deployment-guide.md §3-§4
- Approval required: yes — new endpoint + new migration, then deploy to production
- Approval evidence: session message "once done commit to main branch, push and deploy to prod"

## Completion gates

| Gate | Status | Evidence (command and result, file reference, or N/A reason) |
|---|---|---|
| Requested behavior or artifact is complete | PASS | `GET /admin/integrations/cloudfone/transcripts?day=…` now answers with `day_state` (unchecked/checked/error); `POST /admin/integrations/cloudfone/transcripts/backfill` fetches that day from CloudFone, downloads the recording, transcribes it and stores the rows; the viewer fetches an unchecked day by itself and leaves a checked day alone. Driven in real Chromium: day 2026-10-20 → POST backfill → the row "20/10/2026 17:02 · 0902113344 · 1p38s" rendered; "Xem" → the full transcript; day 2026-10-19 (no calls) → "Ngày này không có bản ghi"; reopening that day → no second vendor call. Artifacts: plans/qa-261021/cloudfone-transcripts-fetched-day.png, plans/qa-261021/cloudfone-transcripts-detail.png, plans/qa-261021/cloudfone-transcripts-known-empty-day.png, plans/qa-261021/cloudfone-transcripts-on-demand.log (driver: plans/qa-261021/cloudfone-transcripts-on-demand.mjs). |
| Diff is limited to the approved scope | PASS | `git status --short` = the 18 listed paths (+ the pre-existing untracked `docs/API.docx`, untouched). No unrelated frontend surface, no dependency or lockfile change. |
| Protected operations were avoided or approved | PASS | The new endpoint is admin-only (`require_admin`), writes only to the two Cloudfone tables, sends no email and touches no other domain. Production was reached read-only (SSH: table counts, settings keys, migration head) before the deploy the user asked for. |
| Focused tests/checks pass | PASS | `pytest tests/test_cloudfone_transcript_backfill.py` → 7 passed; `pytest tests/test_cloudfone_transcripts_api.py` → 8 passed; `pytest tests/integration/test_cloudfone_transcript_store.py` → 8 passed (real DB, migration 0077 applied); frontend `CloudfoneTranscriptsSection.test.tsx` → 9 passed (auto-fetch, checked-day skip, progress state, most-recent-day action). |
| Broader regression tests pass when shared behavior changed | PASS | Backend unit suite → 4094 passed, 28 skipped. Frontend unit suite → 1052 passed (122 files). Route inventory oracle updated (`integrations: 44→45`, digest `4a63541d…`) and green. |
| Lint passes for affected code | PASS | `ruff check` on the 7 changed backend files → All checks passed; `npm run lint` → 0 errors (35 pre-existing warnings elsewhere); `prettier --check` on the touched frontend files → clean (one file reformatted). |
| Type checking passes for affected code | PASS | `npx tsc --noEmit -p tsconfig.app.json` → no output (clean). |
| Build/import validation passes for affected code | PASS | `npm run build` → built in 2.17s; backend app imports exercised by the test run and by the local verification stack (uvicorn boot + real HTTP). |
| Security and privacy impact reviewed | PASS | The endpoint is behind `require_admin`; the vendor credentials stay in the encrypted settings rows (never in a response); the response carries counts and a status only, no transcript text. The on-demand fetch creates no new egress path — it reuses the same vendor call the daily pass makes. |
| Performance and async-I/O impact reviewed | PASS | The list query adds one indexed primary-key lookup (`cloudfone_transcript_days.day`). The fetch is one vendor page walk + one recording download + one STT call per recordable call, capped by the existing `MAX_TRANSCRIPTIONS_PER_DAY` (60); the viewer loops only while the server reports `remaining > 0`. The daily pass is unchanged in cost (one extra upsert per day). |
| Accessibility and Vietnamese UX reviewed for UI changes | PASS | All new copy is Vietnamese; the fetch state is a `role="alert"`-free EmptyState with a spinner icon (`aria-hidden`), the known-empty state offers a labelled "Kiểm tra lại từ Cloudfone" action and the unfiltered empty state a "Tải bản ghi ngày gần nhất" action; the existing labelled filter controls are untouched. |
| Error handling and compatibility reviewed | PASS | Vendor failure → `status: failed` + the day marked `error` (a later attempt may retry, no auto-retry storm); missing credentials or STT key → `unconfigured` before any vendor call; a checked day → `skipped`. The old list response shape is unchanged except for the additive `day_state` field (null without a day filter). |
| Documentation impact handled (includes `node scripts/check-doc-links.mjs` when agent routing changed) | PASS | `docs/ops/deployment-guide.md` §4 Alembic HEAD updated to `0077_cloudfone_transcript_days` (the release gate greps this line). Agent routing did not change, so `check-doc-links.mjs` was not required — it runs inside `make release-check`. |
| No new unlinked `TODO`, `FIXME`, or `HACK` | PASS | `grep -rnE "TODO|FIXME|HACK"` over the changed files → none. |
| Final `git diff --check` passes | PASS | `git diff --check` → clean (no whitespace errors). |
| Final `git status --short` reviewed | PASS | Reviewed: 13 modified, 3 new (`0077` migration, the backfill test, `plans/qa-261021/`) + the pre-existing untracked `docs/API.docx` (the vendor's Cloudfone API document — deliberately NOT committed: it is a binary vendor file that may carry credentials, and it is not the user's request). |

## Result

- Overall status: PASS
- Remaining risks or follow-ups:
  - The on-demand fetch runs inside the request, so a day with many recordable calls can take as long as the daily pass does (the viewer loops over `remaining`). If a real day ever exceeds the 60-call transcription cap in one request, the request should move to a queued job — not needed at the observed volume (≤7 calls/day).
  - The transcripts of the days the daily pass covered before this change are not back-filled automatically; the admin picks the day in the viewer and the fetch stores them.
  - `docs/API.docx` remains untracked in the worktree. It was moved aside (not deleted) while `make release-check` required a clean tree.
