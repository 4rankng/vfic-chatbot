# Agent Completion Checklist

## Task record

- Task: Project settings — 422 save fix, chatbot external-API readiness + test call,
  external-API panel restructure, instant category detail (6-step approved plan,
  `local://project-external-api-plan.md`).
- Scope: `ProjectEdit` minimal PATCH payload; `CategoryEditor` direct YAML render;
  `ProjectChatbotReadiness` projection; `POST /external-api/test` endpoint with per-admin
  rate limit; frontend contracts/service/sectioned panel; docs (api, architecture, summary).
- Files changed: 19 —
  backend: `app/api/projects.py`, `app/schemas/projects.py`, `app/services/project/external_api.py`,
  `app/shared/infrastructure/rate_limits.py`, `tests/test_project_external_api.py`,
  `tests/test_project_external_api_api.py`, `tests/test_runtime_surface_inventory.py`;
  frontend: `projects/ProjectEdit.tsx`, `projects/ProjectEdit.test.tsx`,
  `projects/ProjectExternalApiPanel.tsx`, `projects/ProjectExternalApiPanel.test.tsx`,
  `projects/ProjectKnowledgePanel.test.tsx`, `projects/domain/external-api-contracts.ts`,
  `projects/domain/external-api-policy.test.ts`, `projects/external-api-service.ts`,
  `projects/presentation/CategoryEditor.tsx`;
  docs: `docs/api.md`, `docs/codebase-summary.md`, `docs/system-architecture.md`.
- Instructions retrieved: `AGENTS.md` (always-loaded), the approved inline plan, `skill://browser`
  (live e2e), `xd://bash` / `xd://eval/browser` tool docs.
- Approval required: plan approved by the user before execution; ship instruction
  ("commit, push, deploy to prod") given in-session.
- Approval evidence: this conversation's plan-approval message and the explicit ship instruction.
  No alembic, webhook, auth/JWT/CORS, `app/core/*` protected file, manifest, Makefile, or
  deployment-file edits. `app/shared/infrastructure/rate_limits.py` (adapter, not the protected
  `app/core/ratelimit.py`) was edited exactly as the approved plan specifies.

## Completion gates

| Gate | Status | Evidence (command and result, file reference, or N/A reason) |
|---|---|---|
| Requested behavior or artifact is complete | PASS | All 6 plan steps executed; live browser e2e: PATCH `/api/v1/knowledge/projects/{id}` body exactly `{"name":…,"is_active":true}` → 200 + toast `Đã lưu.` (was 422); category YAML visible 129 ms after one left-card click (no `<details>`, `detailsCount:0`); panel shows 5 section headings + readiness chip `Chưa sẵn sàng · Tích hợp đang tắt; Chưa có bản cài đặt Agent hoạt động`; `POST …/external-api/test` `{"method":"GET","path":"/openapi.json"}` → 200 `state:ok` → UI alert `Thành công · HTTP 200`. |
| Diff is limited to the approved scope | PASS | `git status --short` = the 19 planned files; inventory fixture updated per the plan's own contingency; no unrelated edits. |
| Protected operations were avoided or approved | PASS | No migrations, no `app/core/{config,security,ratelimit}.py`, no auth/webhook/CORS/manifest/Makefile/deploy-file changes; ADR-0011 untouched. Rate-limit adapter + test endpoint are plan-specified and admin-gated. |
| Focused tests/checks pass | PASS | `cd backend && ruff check .` → All checks passed; narrow pytest (external-api + inventory + architecture boundaries) → 86 passed. `cd frontend && npm run lint` clean; `npm run test:unit:app -- src/components/atomic-crm/projects` → 14 files, 94 passed. |
| Broader regression tests pass when shared behavior changed | PASS | `cd backend && .venv/bin/pytest -m "not integration"` → 2467 passed, 24 skipped, 137 deselected. `cd frontend && npm run test:unit:app` → 112 files, 615 passed. |
| Lint passes for affected code | PASS | ruff (backend) and eslint (frontend, whole repo) both exit clean after the change set. |
| Type checking passes for affected code | PASS | `cd frontend && npm run typecheck` (`tsc --noEmit -p tsconfig.app.json`) → no errors. |
| Build/import validation passes for affected code | PASS | `backend/.venv/bin/python -c "import app.services.project.external_api; import app.api.projects"` → `imports ok` (no circular import from the top-level `InstallationService` import); frontend build gate runs in `make release-check` before deploy. |
| Security and privacy impact reviewed | PASS | Sealed key never rendered (masking tests still pass); test route admin-only + per-admin rate limit; no secrets/PII/message content logged; readiness lookup fails soft (`readiness_unavailable`) instead of 500; egress still single-site (`_send`). |
| Performance and async-I/O impact reviewed | PASS | Readiness adds one authority query per admin `GET`/`PUT` view (admin surface only, not the hot bot path); test call reuses the bot's 8 s timeout pool, dedupe and ceiling; page-scope gate deliberately excluded per plan. |
| Accessibility and Vietnamese UX reviewed for UI changes | PASS | Verified in live browser: semantic `h5` section headings, `label`/`aria-label` on all controls, `aria-invalid`/`aria-describedby` on params, chip + alerts in Vietnamese, focus-visible rings on the method select; existing testids/labels preserved (suite passes). |
| Error handling and compatibility reviewed | PASS | Readiness maps `InstallationError`→`installation_required`, other failures→`readiness_unavailable`; test states (`not_configured`/`rate_limited`/`invalid_request`/`error`) mapped in UI; client rejects bad JSON params before sending; strict `ProjectUpdate` schema kept (no relaxation). |
| Documentation impact handled | PASS | `docs/api.md` new "Per-project external API" route table (3 rows); `docs/system-architecture.md` admin-surface bullet extended with the test route + readiness; `docs/codebase-summary.md` rows 182/216 updated. ADR-0011 intentionally untouched (records the past decision). |
| No new unlinked `TODO`, `FIXME`, or `HACK` | PASS | `git diff \| grep -cE "^\+.*(TODO\|FIXME\|HACK)"` → 0. |
| Final `git diff --check` passes | PASS | `git diff --check` → clean (no whitespace errors). |
| Final `git status --short` reviewed | PASS | Only the 19 planned files modified; vitest failure screenshot artifact removed; `__screenshots__/` is gitignored. |

## Result

- Overall status: PASS
- Remaining risks or follow-ups:
  - `make openwiki` has no `OPENROUTER_API_KEY` (checked env and `backend/.env`) → index refresh
    blocked by the Makefile's own guard; recorded as skipped.
  - Local `make dev` bootstrap fails on this machine (`backend/.venv` has no pip) and the dev
    compose's fixed ports 6382/8082 collide with the sibling `kiosk` stack; e2e ran on manually
    started uvicorn/vite plus a session redis on 6395. Dev DB was knowledge-empty, so a RAG KB +
    active `jobs` revision were seeded for `foxconn-nghe-an` (dev DB only, disclosed) and the
    project's `external_api` row restored to its original `NULL`.
  - `chatbot_readiness` intentionally excludes the per-conversation page↔project scope
    (`resolve_page_project_scope`); the test button plus a real chat turn remain the proof for
    that gate.
