# Codebase Tech-Debt Audit — Completion

## Task record

- Task: Audit the codebase for tech debt and fix what is safely fixable.
- Scope: Backend error-handling debt (K-9), the open `lead_stage` PATCH defect
  (K-6), stale/incorrect documentation (K-3 and the testing sections), and three
  frontend stale-closure lint defects. Debt register refreshed.
- Files changed: 32 modified + 1 new test (list below); **plus 44 generated
  `openwiki/` pages modified by an unrelated interrupted MCP process — see
  "Out-of-scope repository change" below.**
- Instructions retrieved: `AGENTS.md`, `docs/code-standards.md`,
  `docs/project-roadmap.md`, `standards/agent-completion-checklist.md`,
  `TECH.md`, `backend/tests/test_architecture_boundaries.py`.
- Approval required: No. No protected path was edited (see gate 3).
- Approval evidence: N/A.

### Files changed

Backend — application: `app/shared/domain/errors.py`, `app/core/errors.py`,
`app/api/{auth,auth_dependencies,bot_runs,conversations,installation_dependencies,integrations,jobs,knowledge,leads,personas,projects,users}.py`,
`app/composition/conversation_messaging.py`.

Backend — tests: `test_access_policies.py`, `test_conversation_channel_provider.py`,
`test_conversation_history_clear.py`, `test_external_source_sync_api.py`,
`test_facebook_oauth.py`, `test_generic_api_guards.py`,
`test_identity_authentication.py`, `test_persona_assignments_api.py`,
`test_web_chat_endpoint.py`, new `test_lead_update_concurrency.py`.

Frontend: `hooks/useMasterDetailSelection.ts`,
`knowledge/KnowledgeVersionManager.tsx`,
`knowledge-base/KnowledgeBaseShow.tsx`,
`login/useResendCooldown.ts`,
`dashboard/RecruitingCommandCenter.render.test.tsx`.

Docs: `docs/code-standards.md`, `docs/project-roadmap.md`,
`docs/troubleshooting/README.md`.

## Completion gates

| Gate | Status | Evidence (command and result, file reference, or N/A reason) |
|---|---|---|
| Requested behavior or artifact is complete | PASS | K-9: `grep -rn "raise HTTPException" backend/app/api/` → 0 hits (was 64 across 12 routers). K-6 fixed and regression-tested. Docs corrected. Register refreshed. |
| Diff is limited to the approved scope | PASS | `git status --short \| grep -v openwiki \| wc -l` → 33 files, all listed above. No unrelated application code touched. |
| Protected operations were avoided or approved | PASS | No edit to `alembic/versions/*`, `.env`, `config.py`/`security.py`/`ratelimit.py`, webhooks, manifests, `docker-compose*`, `Caddyfile`, `index.css`, or any `Makefile`. `app/core/ratelimit.py` left raising its own 429 by design. No migration, schema, dependency, or deploy change. |
| Focused tests/checks pass | PASS | `pytest tests/test_lead_update_concurrency.py` → 1 passed. New test proven to fail pre-fix (`KeyError: 'version'`) and pass post-fix. |
| Broader regression tests pass when shared behavior changed | PASS | `pytest -m "not integration"` → **2313 passed, 21 skipped** (baseline was 2312 passed; +1 is the new test). `vitest --project app --run` → **107 files, 569 tests passed**. |
| Lint passes for affected code | PASS | `ruff check app/ tests/` → "All checks passed!". `eslint src/**/*.{ts,tsx}` → 0 errors, 16 warnings (all pre-existing `react-refresh/only-export-components`, a rule the project configures at `warn` and CI does not gate on; down from 21). |
| Type checking passes for affected code | PASS | `tsc --noEmit --project tsconfig.app.json` → exit 0. |
| Build/import validation passes for affected code | PASS | `import app.main` succeeds; every converted router imports cleanly under ruff and pytest collection. |
| Security and privacy impact reviewed | PASS | Error-path change preserves status/body/headers exactly (proved for all 9 error classes). No secret logged or exposed. One pre-existing disclosure smell found and **recorded, not silently changed** — K-11. |
| Performance and async-I/O impact reviewed | PASS | No new I/O. Error classes are plain exception objects; the new handler does one dict lookup instead of the previous per-class map. Frontend fixes *remove* a per-render effect churn in `useMasterDetailSelection`. |
| Accessibility and Vietnamese UX reviewed for UI changes | PASS | Frontend change is a `useCallback`/dependency-stability refactor plus two type-only imports; no markup, copy, or styling change. All Vietnamese server messages preserved byte-for-byte (asserted in tests). |
| Error handling and compatibility reviewed | PASS | Contract parity proved for 404/409/403/400/422/429/502/410/401 including the dict `{"errors": [...]}` 422 body, the runtime 409-vs-400 branch in `knowledge.py`, and `InstallationError`'s rich payload. One deliberate delta documented in K-9: `/auth/login` and `/auth/refresh` 401s now carry `WWW-Authenticate: Bearer` (status and body unchanged; RFC 7235 requires a challenge on 401). |
| Documentation impact handled | PASS | `docs/code-standards.md` documents the new taxonomy and the fixture-registration requirement; testing section corrected; `docs/troubleshooting/README.md` dev Redis default corrected; `docs/project-roadmap.md` K-3 corrected, K-6/K-9 closed with evidence, K-11/K-12 added. |
| No new unlinked `TODO`, `FIXME`, or `HACK` | PASS | None added. |
| Final `git diff --check` passes | PASS | `git diff --check` → clean (no whitespace errors). |
| Final `git status --short` reviewed | PASS | Reviewed; my 33 files enumerated above. The 45 `openwiki/` entries are an unrelated interrupted MCP write — see below. |

## Out-of-scope repository change (not mine — flag for the owner)

`git status` shows **44 modified generated `openwiki/*.md` pages + untracked
`openwiki/.run.json`** that I did not author. The tree was clean at session start.

Cause: an `openwiki mcp --host opencode` process (PID 21620, started 10:41) ran an
`update`, which **interrupted at 10:48:57** — see `openwiki/.last-update.json`:
`status: "interrupted"`, `model: "host-agent/opencode"`, and a recorded `gitHead`
of `6dc7e8e2…` that is **not** current HEAD (`09137ff2`).

Effect: the regenerated pages lost their `verified:` frontmatter blocks (provenance
metadata). Per `AGENTS.md` ("do not hand-edit generated OpenWiki pages") I left
them untouched rather than reverting generated output unilaterally. **Recommend
the owner either re-run a complete `openwiki update` or
`git checkout -- openwiki/` before committing**, so a partially generated
degradation is not committed.

## Result

- Overall status: **COMPLETE** for the audited and fixed items; three debt items
  intentionally left open because they need a product or owner decision.
- Remaining risks or follow-ups:
  - **K-4** — logout-on-browser-close remains a product call (unchanged).
  - **K-10** — malformed character data needs a scoped data-remediation
    migration (approval-gated; unchanged).
  - **K-11** — web-chat 500s echo raw exception text. Preserved exactly for
    contract safety and recorded rather than silently changed. Owner should
    confirm whether the raw detail is still wanted for debugging.
  - **K-12** — 16 `react-refresh/only-export-components` warnings across 9
    frontend modules. Deliberately tolerated by project config and CI; dev-only
    HMR impact. Fixing means extracting exports and updating importers.
  - **Unverified here:** the DB-backed integration lane (82 tests) needs the
    local pgvector service and was not run. It is unaffected by these changes in
    principle, but the error-path conversion does touch routers those tests
    exercise — run `docker compose -f docker-compose.dev.yml up -d postgres`
    before merging if you want that closed out.
  - No commit, push, branch, or PR was created (per repository workflow).
