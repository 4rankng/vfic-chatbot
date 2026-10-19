# Agent Completion — ODS CloudFone client theo spec 1.1 (GetCallLogs)

## Task record

- Task: Fix the ODS CloudFone client to the GetCallLogs API spec 1.1
  (branch `fix-ods-apicall-1-1`, brief `fix-ods-apicall-1-1`): spec-named auth
  (ServiceName + AuthUser + AuthKey as three admin settings), required
  paging/date fields (Direction, DateStart, DateEnd, PageIndex, PageSize),
  success-envelope handling, spec-conformant `/ods/test` probe
  (PageIndex 0, PageSize 5), and spec-conformant daily insights fetch
  (00:00:01 → 23:59:59 of the previous ICT day, IsSort=1).
- Scope: backend client + settings provider + API schemas + test endpoint +
  tests; frontend settings section + API gateway + tests. No route added or
  removed; no schema/migration change.
- Files changed:
  - `backend/app/services/ods.py`
  - `backend/app/services/integration_settings/providers/ods.py`
  - `backend/app/services/integration_settings/__init__.py`
  - `backend/app/schemas/integrations.py`
  - `backend/app/api/integrations.py`
  - `backend/tests/test_ods_service.py`
  - `backend/tests/test_ods_settings.py`
  - `backend/tests/test_ods_worker.py`
  - `frontend/src/components/atomic-crm/integrations/api.ts`
  - `frontend/src/components/atomic-crm/integrations/OdsSection.tsx`
  - `frontend/src/components/atomic-crm/integrations/OdsSection.test.tsx`
- Instructions retrieved: root `AGENTS.md`, `frontend/AGENTS.md`,
  `standards/agent-completion-checklist.md`.
- Approval required: none beyond the task brief (commit + merge to main
  explicitly requested by operator).
- Approval evidence: operator instruction "consolidate change and merge to
  main branch" (this session).

## Completion gates

| Gate | Status | Evidence (command and result, file reference, or N/A reason) |
|---|---|---|
| Requested behavior or artifact is complete | PASS | `OdsCloudfoneClient` posts `ServiceName`/`AuthUser`/`AuthKey` + `Direction`/`DateStart`/`DateEnd`/`PageIndex`/`PageSize` (asserted in `tests/test_ods_service.py::test_get_call_logs_sends_the_spec_1_1_body`); legacy `Service`/`APIKey`/`Limit` asserted gone; daily fetch uses `00:00:01→23:59:59` + `IsSort=1` with bounded paging; `/ods/test` probes one page of 5; result≠success raises with message (live `result:"failure"` envelope test). |
| Diff is limited to the approved scope | PASS | `git status --short`: the 11 files listed above only; all ODS surfaces. |
| Protected operations were avoided or approved | PASS | Merge to main + push explicitly requested by operator; no deploy, no image build. |
| Focused tests/checks pass | PASS | `pytest tests/test_ods_service.py tests/test_ods_settings.py tests/test_ods_worker.py -q` → 35 passed. `npx vitest run src/components/atomic-crm/integrations` → 9 files, 86 tests passed. |
| Broader regression tests pass when shared behavior changed | PASS | Backend unit lane `pytest tests -q --ignore=tests/integration` → 4019 passed, 9 failed; the same 9 fail identically on main `c26d5589` (run on the main checkout) — pre-existing, unrelated (deployment-makefile + route-inventory snapshots). Full run: 337 errors all `tests/integration/*` Postgres-connection setup failures (docker DB not running in this environment; environmental, present on main too). Frontend full unit suite → 121 files, 1042 tests passed. |
| Lint passes for affected code | PASS | `ruff check app tests` → all clean; `ruff format` applied. `npm run lint` → 0 errors, 35 warnings — byte-identical count to main. Prettier applied to touched files. |
| Type checking passes for affected code | PASS | `npm run typecheck` clean. `uvx pyright` on the four changed backend modules → 1 error at `app/api/integrations.py:413` (`EmailDigestTestOut` return) that exists identically on main; ODS code introduces none. |
| Build/import validation passes for affected code | PASS | `npm run build` completes; backend modules import-clean via full test collection (4019 tests import the changed modules). |
| Security and privacy impact reviewed | PASS | `auth_key` stays secret: encrypted at rest (`is_secret=True`), masked via `_secret_status` in the admin view, never logged, never in URLs (asserted `"cf-key" not in seen["url"]`). `service_name`/`auth_user` are non-secret config. Legacy `ods_api_key` row remains a read-only fallback. |
| Performance and async-I/O impact reviewed | PASS | All I/O stays async through the shared http client; daily fetch bounded at `MAX_DAILY_PAGES = 5 × 200` rows with a truncation warning instead of an unbounded loop; probe is a single page. |
| Accessibility and Vietnamese UX reviewed for UI changes | PASS | Reuses `PlainField`/`SecretField` (existing labelled, accessible fields); Vietnamese-only copy; badge count updated to 4 configured fields; status line explains missing pieces. |
| Error handling and compatibility reviewed | PASS | `result != "success"` → `CloudfoneError` with vendor message or "không rõ lý do"; missing credentials reported per field (`service_name`/`auth_user`/`auth_key`); garbage `total` falls back to the page length; legacy single-key deployments keep resolving. |
| Documentation impact handled | PASS | No doc describes the ODS request fields (`grep` across `docs/`); `node scripts/check-doc-links.mjs` → "Agent routing OK: 32 paths and 4 make targets". |
| No new unlinked `TODO`, `FIXME`, or `HACK` | PASS | `grep` over all touched source files → 0 matches. |
| Final `git diff --check` passes | PASS | `git diff --check` → clean. |
| Final `git status --short` reviewed | PASS | Reviewed before staging; only the 11 in-scope files. |

## Result

- Overall status: PASS
- Remaining risks or follow-ups:
  - Pre-existing on main, not touched here: 9 backend unit failures
    (deployment-makefile + runtime-surface-inventory snapshots) and 1 pyright
    error at `app/api/integrations.py:413`.
  - Integration lane requires the dev Postgres (docker) and was not runnable
    in this environment; the release `data` lane remains an owner run.
  - The `ods_insights_worker` still fetches a single day bounded at 1000 rows;
    past that the email ships truncated with a warning logged.
