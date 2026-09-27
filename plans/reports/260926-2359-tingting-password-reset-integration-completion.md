# Agent Completion Checklist

## Task record

- Task: make the chatbot actually run the TingTing employee password-reset flow — deployment-wide
  integration, embedded workflow guide, admin supplies only the API key; stop the refusal-with-
  invented-hotline behaviour.
- Scope: backend (integration settings group, service, port/repository seam, tool, prompt guide,
  routing intent, grounding guard, settings API) + frontend (settings console section) + docs/ADRs.
- Files changed:
  - new: `backend/app/services/tingting_api.py`, `backend/app/graph/tingting_guide.py`,
    `backend/app/graph/tools/tingting_api.py`,
    `backend/app/services/integration_settings/providers/tingting.py`,
    `backend/tests/test_tingting_api.py`,
    `frontend/src/components/atomic-crm/integrations/presentation/TingtingSection.tsx`,
    `docs/decisions/0012-tingting-password-reset-integration.md`
  - edited: `backend/app/graph/{runner,router,decisions,context,grounding,schemas,ports,runtime_policy,
    persona.md,tools/__init__}.py` (persona.md), `backend/app/schemas/{bot_run,integrations}.py`,
    `backend/app/api/integrations.py`, `backend/app/services/project/external_api.py`,
    `backend/app/services/retrieval/repository.py`,
    `backend/app/services/integration_settings/service.py`, `backend/app/graph/clients.py`,
    frontend `integrations/{api.ts,ZaloIntegrationPage.tsx,ZaloIntegrationPage.navigation.test.tsx,
    settings.css.test.ts,presentation/settingsNav.ts}`,
    `projects/ProjectExternalApiPanel.tsx`, tests under `backend/tests/`, docs
    (`system-architecture.md`, `codebase-summary.md`, `decisions/0011-*.md` status marker).
- Instructions retrieved: `AGENTS.md`, `docs/system-architecture.md` §14, `docs/codebase-summary.md`,
  `docs/decisions/0011-per-project-external-api-guide.md`, `standards/agent-completion-checklist.md`,
  neighbouring code (`services/project/external_api.py`, `graph/runner.py`, `graph/schemas.py`,
  `integration_settings/*`, frontend settings console).
- Approval required: yes — bot prompts/grounding, routing policy and tool definitions are
  approval-gated in `AGENTS.md`.
- Approval evidence: the user directed the change in-conversation ("please make change to frontend
  and backend… this reset mat khau feature does not need to link to any particular project… admin
  just need to provide API key"), and approved the routing+injection fix option via the `ask` tool.

## Completion gates

| Gate | Status | Evidence (command and result, file reference, or N/A reason) |
|---|---|---|
| Requested behavior or artifact is complete | PASS | Password reset is a deployment-wide integration: admin sets one key (`GET/PUT /api/v1/admin/integrations/tingting`), the guide is embedded (`app/graph/tingting_guide.py`), the prompt block is injected whenever the key is configured regardless of project focus, and `call_tingting_api` performs the four endpoints against the fixed TingTing origin. Guide enforces name+CCCD+mobile verification before the OTP step. |
| Diff is limited to the approved scope | PASS | Only the reset-flow surface, its tests, and its docs; the per-project integration keeps its behaviour (`docs/decisions/0011-*.md` status marked superseded-in-part per ADR rules). |
| Protected operations were avoided or approved | PASS | No Alembic version, `.env`, dependency, deployment file or auth/CORS/rate-limit change. New settings endpoints are admin-only, mirroring the existing integration settings routes, and were explicitly requested. |
| Focused tests/checks pass | PASS | `pytest tests/test_tingting_api.py -q` → 21 passed; `pytest tests/test_grounding.py tests/test_graph_decisions.py tests/test_integrations_api.py tests/test_graph_runner_turn.py -q` → passed; `vitest run src/components/atomic-crm/integrations` → 47 passed. |
| Broader regression tests pass when shared behavior changed | PASS | `pytest tests/ -q --ignore=tests/integration` → 2504 passed, 24 skipped (runtime-surface baselines refreshed with documented deltas: provider_boundary 83→86, integrations routes 31→33, both reviewed fingerprints re-recorded). |
| Lint passes for affected code | PASS | `ruff check` on all changed backend modules → "All checks passed!". `eslint` on changed frontend files → 0 errors (react-refresh warning removed by making the query key module-local). |
| Type checking passes for affected code | PASS | `npx tsc --noEmit --project tsconfig.app.json` → clean. |
| Build/import validation passes for affected code | PASS | Backend imports exercised by the full pytest collection (2504 tests). No frontend build run (not required for this task); `tsc` + vitest cover the changed modules. |
| Security and privacy impact reviewed | PASS | Key stored AES-GCM-encrypted, status-only admin read (`{configured, preview}`), never logged, never in the prompt, sent only as the `X-API-Key` header; origin fixed in code with a validated override; relative-path-only validation, `GET`/`POST` only, flat bounded params, no error body echoed, shared dedupe/ceiling quota (fail-open). Guide forbids revealing key/session/token and treats API payloads as data. |
| Performance and async-I/O impact reviewed | PASS | One primary-key SELECT per turn when configured (prompt gate) plus one on the tool call; single outbound httpx request through the shared client; no new background work, no blocking calls. |
| Accessibility and Vietnamese UX reviewed for UI changes | PASS | Section reuses the existing console components (`SettingsSectionPanel`/`SettingsGroup`/`SecretField`) and the existing Vietnamese copy/notify patterns; no new interaction model, keyboard behaviour unchanged. |
| Error handling and compatibility reviewed | PASS | Every outcome is a state the model can state truthfully (`ok`/`error`/`invalid_request`/`rate_limited`/`not_configured`); configuration read failures cannot break a turn (prompt gate catches, repository degrades to `not_configured`); no existing tool/route/endpoint contract changed except additive ones (new intent `employee_support`, new route, new tool, additive trace literals). |
| Documentation impact handled | PASS | ADR-0012 added, ADR-0011 marked superseded-in-part, `docs/system-architecture.md` §14b added (+ readiness blocker note), `docs/codebase-summary.md` module rows added. |
| No new unlinked `TODO`, `FIXME`, or `HACK` | PASS | `grep -rn "TODO\|FIXME\|HACK"` over the changed files returned nothing new. |
| Final `git diff --check` passes | PASS | `git diff --check` → no whitespace errors. |
| Final `git status --short` reviewed | PASS | 32 modified + 7 new files, all inside the approved scope. |

## Follow-up task (same session): retire the per-project external API

- Removed at the product owner's direction (approved option: full code teardown, keep the column):
  the project settings panel + its service/policy/contracts/tests, the
  `GET`/`PUT`/`POST /knowledge/projects/{id}/external-api` routes, `ProjectExternalApiService` and
  its schemas, `call_project_api` (tool module, schema, registry, dispatch, knowledge-capability
  grant, decision-trace literal, prefetch scoping), the FOCUSED-turn prompt block, the
  `enforce_external_api_test_rate_limit` helper, and the two project-integration test modules.
- Shared primitives moved to `app/services/external_api_core.py` (transport-free); the TingTing
  service now imports from there and keeps its own single egress site.
- `projects.external_api` stays as an unread nullable column (documented on the model).
- Evidence: `pytest tests/ -q --ignore=tests/integration` → 2433 passed, 24 skipped;
  `ruff check app/ tests/` clean; `tsc --noEmit` clean; `vitest` atomic-crm suite → 103 files /
  559 tests passed; runtime-surface counts refreshed (projects 31→28 routes, provider_boundary
  86→85) with both reviewed digests recomputed.
- Settings page reachability verified by `ZaloIntegrationPage.navigation.test.tsx` (15 passed):
  the console renders the TingTing nav entry, opens the section, exposes the `API key TingTing`
  field, and keeps Save disabled until a key is typed.

## Deployment (production, 2026-09-27)

- `make deploy` (approved by the product owner in-session) — tag `13dee9ba`, blue/green backend
  (`bg_deploy done. active=web-blue`), `PIPELINE OK: consumers live, no conversation awaiting a
  reply, outbox drained`, frontend container recreated from the same tag.
- First attempt failed in `release-check` at `npm run registry:check` (nothing was built, pushed or
  deployed): `frontend/registry.json` still listed the four deleted project external-API modules and
  did not publish `TingtingSection.tsx`. Fixed with `npm run registry:gen` (diff: −4 paths, +1) and
  committed as `13dee9ba`.
- After-checks against production:
  - `GET /api/v1/admin/integrations/tingting` → **404 before / 401 after** (sibling `/jev` → 401);
    `/health` → 200.
  - Deployed chunk `assets/ZaloIntegrationPage-Y1i4HdWP.js` is byte-identical to the local build
    (sha256 `cb8eeb0b67a856c3`, 59 697 B) and contains `TingTing`, `Đặt lại mật khẩu` and
    `tingting_api_key`.
- Operator action still required: paste the TingTing API key into *Cài đặt → TingTing · Đặt lại mật
  khẩu*; until then the section reports `configured: false` and the guide stays out of the prompt.

## Git housekeeping (same session)

- Transient OpenWiki run-state files untracked + gitignored: `openwiki/.run.json`,
  `openwiki/.last-update.json` (`.gitignore:119-120`); both remain on disk.
- The two unpushed commits were rebuilt so the run-state files never appear in them
  (`273a2e49` → now `6967c6c0` on top); `git diff <old HEAD> main` was empty, i.e. the final tree is
  unchanged. Old commits remain in the reflog.

## Result

- Overall status: PASS
- Remaining risks or follow-ups:
  - The live TingTing key is not configured on the deployed instance (the admin panel showed
    "Chưa cấu hình"); until an operator saves a key, the guide is absent and the bot falls back to
    an honest hand-off. That is by design and is now visible as `configured: false` in the settings
    section.
  - `make openwiki` (AGENTS step 7): BLOCKED — the target exits with
    `OpenWiki blocked: no OpenRouter key. Export OPENROUTER_API_KEY or fill it in backend/.env.`
    Neither the environment nor `backend/.env` carries the key, so the generated index was not
    refreshed. This task did change documented architecture (§14b + ADR-0012), so the index must be
    regenerated once a key is available.
  - The contact guard activates only at call sites that pass the prompt text (`clients.agent`,
    progressive runner sites); a future call site that omits `allowed_text` would silently skip it.
