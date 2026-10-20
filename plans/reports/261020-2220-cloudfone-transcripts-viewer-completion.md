# Agent Completion Checklist

Copy this file to
`plans/reports/<YYMMDD-HHmm>-<slug>-completion.md` for each implementation task.
Replace every `PENDING` with `PASS`, `N/A`, or `BLOCKED`. A task is not complete
while any item is `PENDING` or `BLOCKED`.

## Task record

- Task: Admin viewer for stored CloudFone voice-call transcripts (Untitled UI Pro design), opened from a button in the Cloudfone settings section
- Scope: read-only list+detail API over `cloudfone_call_transcripts`; transcripts page (filters, table, pagination, detail panel) built from the vendored Untitled UI primitives per `frontend/AGENTS.md` § UI/UX Component Sourcing; button in CloudfoneSection; console wiring
- Files changed: backend/app/services/cloudfone_transcripts.py, backend/app/schemas/integrations.py, backend/app/api/integrations.py, backend/tests/test_cloudfone_transcripts_api.py (new), backend/tests/integration/test_cloudfone_transcript_store.py, backend/tests/test_runtime_surface_inventory.py, frontend/src/components/atomic-crm/integrations/CloudfoneTranscriptsSection.tsx (new), frontend/src/components/atomic-crm/integrations/CloudfoneTranscriptsSection.test.tsx (new), frontend/src/components/atomic-crm/integrations/CloudfoneSection.tsx, frontend/src/components/atomic-crm/integrations/CloudfoneSection.test.tsx, frontend/src/components/atomic-crm/integrations/SettingsChrome.tsx, frontend/src/components/atomic-crm/integrations/SettingsConsolePage.tsx, frontend/src/components/atomic-crm/integrations/settingsNav.ts, frontend/src/components/atomic-crm/integrations/api.ts, frontend/e2e/cloudfone-transcripts.spec.ts (new), docs/ops/deployment-guide.md (Alembic HEAD line)
- Instructions retrieved: session messages ("the web should allow admin to view transcript of the voice call… untitled UI pro to help with design a page… the page will appear if click a button in the cloudfone setting page", "do it properly")
- Approval required: yes — new feature
- Approval evidence: session message requesting the viewer page + ak-agentkit route accepted

## Completion gates

| Gate | Status | Evidence (command and result, file reference, or N/A reason) |
|---|---|---|
| Requested behavior or artifact is complete | PASS | Button "Xem bản ghi cuộc gọi" in the Cloudfone settings footer → transcripts view (filter bar: call day + phone fragment; UUI table: time/phone/duration/preview + per-row Xem; count strip + pagination; detail panel with full transcript). Design source: UUI PRO `settings-01/09` + `informational-02/03` anatomy, implemented with the repo's vendored UUI v8 primitives. Wired end-to-end verified in real Chromium via Playwright e2e (settings → button → API 200 → render → back) + screenshot reviewed (labels clean, header copy correct, empty state in place). |
| Diff is limited to the approved scope | PASS | `git status --short` = the 16 listed files; no schema/frontend-settings changes beyond the viewer; no new migration (reuses 0076's table). |
| Protected operations were avoided or approved | PASS | Read-only endpoints behind `require_admin`; no secrets in payloads (transcript content is existing PII, admin-gated). |
| Focused tests/checks pass | PASS | 4 API contract tests (preview ≤160, list/detail split, 404 Vietnamese reason, query bounds) + 3 real-DB query tests (day/caller filters, newest-first pagination, get-by-id) + 6 frontend component tests + 1 wired e2e — all green. |
| Broader regression tests pass when shared behavior changed | PASS | Backend unit suite → 4083 passed, 28 skipped; frontend unit suite → 1048 passed (122 files); route inventory oracle updated with dated delta (`integrations: 42→44`, digest `9f8492ed…`) and green. |
| Lint passes for affected code | PASS | `ruff check app tests` clean; `eslint` on the 7 changed frontend files → 0 problems. |
| Type checking passes for affected code | PASS | `npm run typecheck` clean; earlier `uvx pyright` 0 errors on changed backend files. |
| Build/import validation passes for affected code | PASS | Backend module imports exercised by the test run; frontend `npm run build` runs in the release-check lane. |
| Security and privacy impact reviewed | PASS | Endpoints are admin-only (`require_admin`), read-only, and return only stored call metadata + transcript text; no new egress. Transcript PII retention remains the previously recorded open data-owner decision. |
| Performance and async-I/O impact reviewed | PASS | List queries: indexed `day`, unique `call_id`, bounded page_size ≤100, 160-char preview keeps pages light; detail is a single indexed lookup. |
| Accessibility and Vietnamese UX reviewed for UI changes | PASS | React Aria table semantics (row headers, aria-labels), aria-live pager region, focusable action buttons, Vietnamese copy throughout; labels render without spurious required markers (verified in screenshot); e2e asserts visible Vietnamese strings. |
| Error handling and compatibility reviewed | PASS | 404 with `NotFoundError` Vietnamese reason; loading skeleton / error EmptyState with retry / filtered-empty vs never-stored copy; detail panel fail-soft. Row cells deliberately hold no selection state (React Aria rows memoize per item) — documented at the action column. |
| Documentation impact handled (includes `node scripts/check-doc-links.mjs` when agent routing changed) | PASS | `docs/ops/deployment-guide.md` §4 Alembic HEAD updated to `0076_cloudfone_call_transcripts` (also repairs the drift the previous deploy shipped with, since that release bypassed `release-check`); `check-doc-links.mjs` → "Agent routing OK". |
| No new unlinked `TODO`, `FIXME`, or `HACK` | PASS | grep over new/changed files → 0 hits. |
| Final `git diff --check` passes | PASS | CLEAN. |
| Final `git status --short` reviewed | PASS | Exactly the scope list (16 files + this record + the journal entry). |

## Result

- Overall status: PASS
- Remaining risks or follow-ups: (1) PII retention/TTL for stored transcripts (carried over, data-owner decision). (2) Optional: `Cache-Control: no-store` on transcript responses to match the credentials-reveal precedent — currently consistent with the rest of the integrations read API. (3) React Aria table rows memoize per item object: future cell content must stay state-independent (code comment at the action column).
