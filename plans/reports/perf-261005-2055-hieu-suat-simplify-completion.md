# Hiệu suất chatbot simplification — completion record

## Task record

- Task: Reduce `#/hieu-suat` to two metrics (chatbot response time over 1d/7d/1m/3m/6m,
  candidate-phone conversion over the same periods), remove the **Nhật ký bot** screen
  (`/bot_runs`) end to end, polish the mobile layout, delete the dead code.
- Scope: backend `app/reporting/infrastructure/performance_dashboard.py`,
  `app/api/performance.py`, `app/api/bot_runs.py`, `app/services/bot_run_service.py`,
  `app/schemas/bot_run.py`, `app/main.py`, `app/services/slo_service.py` (docstrings);
  frontend `performance/*`, `reporting/domain/*`, `capabilities/*`, `providers/*`,
  `root/*`, `layout/*`, `login/*`, `types.ts`, tests, e2e/QA scripts, `vitest.config.ts`,
  `registry.json`, `package.json`; docs `frontend/AGENTS.md`,
  `docs/architecture/{api,system-architecture}.md`, `docs/ops/{qa-runbook,deployment-guide}.md`,
  `docs/product/overview-pdr.md`.
- Files changed: 82 in the working tree at commit time; delivered as commits
  `e00740fa` (bot-run resource removal), `dfde3e24` (response-time chart, shared
  formatting, flatter page), `fe7e6610` (retired dashboard domain helpers),
  `62f53945` (QA/ops docs + KB-refresh record), `1577a950` (per-criterion extraction
  fake in the knowledge-ingestion tests); `5ead3cd6` (digest cap) landed in the same
  window from the parallel session.
- Instructions retrieved: `AGENTS.md`, `docs/architecture/system-architecture.md`,
  `docs/development/code-standards.md`, `docs/development/testing.md`,
  `docs/architecture/api.md`, `docs/ops/deployment-guide.md` (in full), `frontend/AGENTS.md`,
  `standards/agent-completion-checklist.md`.
- Approval required: yes (commit + push + production deploy).
- Approval evidence: user instruction in-session — "fix all issues, commit, push and deploy
  to prod" (2026-10-05).

## Completion gates

| Gate | Status | Evidence |
|---|---|---|
| Requested behavior or artifact is complete | PASS | Two panels only (`Thời gian phản hồi`, `Tỷ lệ thu được số điện thoại`) over 1d/7d/1m/3m/6m; `/bot_runs` screen, route, nav entry, resource contribution, provider method, API router/service/schema deleted; dead perf components/helpers removed (`performance/presentation/`, `PerformanceTrendChart.tsx`, `performanceDiagnostics.ts`, `dashboardMetrics.ts`). |
| Diff is limited to the approved scope | PASS | Working tree matched the approved plan file-by-file; the only additions beyond the plan are the shared `performanceFormat.ts` (see Notes), the mirrored frontend ratchet in `dataProvider.test.ts`, and stale-doc corrections the change falsified. |
| Protected operations were avoided or approved | PASS | No deploy, commit, push or branch was performed before the user's explicit instruction; the parallel session's commits were left untouched. |
| Focused tests/checks pass | PASS | Backend: `pytest tests/test_performance_endpoint.py tests/test_lead_viewer_scope.py tests/test_faq_bypass_lane_removal.py tests/test_runtime_surface_inventory.py tests/test_frontend_api_contract.py -q` → 81 passed. `pytest tests/integration/test_knowledge_ingestion.py -q` → 19 passed (after the fake-LLM fix). Frontend: `npx vitest --project app run src/components/atomic-crm/performance src/components/atomic-crm/providers/rest` → 25 passed; full perf dir 19 passed. |
| Broader regression tests pass when shared behavior changed | PASS | Backend unit lane `pytest tests/ -q -m "not integration"` → **3618 passed, 28 skipped, 1 failed, 1 error**; both non-passes are environmental: `test_compose_probe_runtime.py::test_the_edge_probe_does_not_follow_the_redirect_off_the_container` ("the stub listener never started answering on 127.0.0.1:80") and one leaked integration test whose `alembic upgrade head` hit its 120 s timeout while three lanes shared the machine. The full *integration* lane was not re-run after the fix: its first pass ran under the same contention and produced 307 identical `alembic upgrade head` timeouts (Docker restarted mid-session and all dev containers — this repo's and every sibling project's — exited 255). Frontend: full `test:unit:app:coverage` → pass, global 82.9/75.24/74.75/84.87 vs floors 67/55/57/68, and the retargeted per-file gate on `PerformanceResponseTimeChart.tsx` ≥80 passes. |
| Lint passes for affected code | PASS | `npm run lint` → 0 errors (35 pre-existing vendored warnings); `npx eslint <changed dirs>` → clean. `ruff check` on every changed backend file → "All checks passed!". |
| Type checking passes for affected code | PASS | `npm run typecheck` → clean. |
| Build/import validation passes for affected code | PASS | `npm run build` → built in 6.25 s; `npm run smoke:built` → "Built bundle boots: the login screen rendered with no page errors". `npm run registry:check` → "Registry paths and local text dependencies are complete (215 files)" after the pre-commit hook regenerated `registry.json`. |
| Security and privacy impact reviewed | PASS | Removing the bot-run list/detail endpoints *narrows* the read surface (draft reply text is no longer exposed through HTTP) and drops a screen that rendered candidate message content. The conversion metric reads only `messages.sender`, `conversations.contact_id`, `leads.contact_id` and non-disavowed `lead_events` payloads through the existing admin-only route. No new secret, no new logging. `npm audit --omit=dev --audit-level=high` → only the four standing moderates (no high/critical). |
| Performance and async-I/O impact reviewed | PASS | The dashboard payload drops from nine concurrent reads to three, and the trend bucket size scales with the window (1800/10800/86400/86400/604800 s) so long windows stay at ≈48/56/30/90/26 points instead of tens of thousands. `_CACHE_TTL_SECONDS = 30` and the Redis wrappers are unchanged. |
| Accessibility and Vietnamese UX reviewed for UI changes | PASS | Each panel has an `h2`, a sub-line and a plain-language value; the chart carries a clipped `<table>` mirror (`performance-trend-data`) so the series is not chart-only; the empty states are text, not blank plots; the period switcher keeps its `aria-label="Khoảng thời gian"`; the volume/rate wording is Vietnamese with `vi-VN` number formatting ("3,2 giây", "25%"). Mobile: the period control scrolls inside its own strip, panels collapse to one `minmax(0, 1fr)` column, and controls keep the 44 px touch target. |
| Error handling and compatibility reviewed | PASS | `window=1h` is now rejected with 422 (pinned by a route-level test); every other `window` value in the closed set validates. `candidate_chats == 0` returns `rate_pct: null` (rendered "—"), never a divide-by-zero. A null p95 keeps the plot gap and prints "—". The `BotRun` table and model stay, so `/admin/performance/slos` and the reconcile paths are unaffected. |
| Documentation impact handled | PASS | `node scripts/check-doc-links.mjs` → "Agent routing OK: 32 paths and 4 make targets across 4 documents all resolve." Docs updated where the change falsified them: `frontend/AGENTS.md` (resource table + tree), `docs/architecture/api.md` (router table 14→13, bot-run section removed), `docs/architecture/system-architecture.md` (bot-run audit paragraph, performance endpoint row), `docs/ops/qa-runbook.md`, `docs/ops/deployment-guide.md`, `docs/product/overview-pdr.md`. |
| No new unlinked `TODO`, `FIXME`, or `HACK` | PASS | None introduced. |
| Final `git diff --check` passes | PASS | `git diff --check` clean at commit time; tree clean after `1577a950`. |
| Final `git status --short` reviewed | PASS | Clean (only the report file itself expected afterwards). |

## Result

- Overall status: **PASS with one unverified lane** — the code, tests, build and docs
  are green and pushed (`810c2139..1577a950 main -> main`). Two verification steps from
  the plan remain unrun for environment reasons: the Playwright `vfic.spec.ts` sweep
  (its disposable backend is hard-coded to port 8000, which this machine's long-running
  dev uvicorn already owns, and `reuseExistingServer: false` makes that a hard error),
  and the dev-stack metric smoke (the dev Postgres/Redis containers exited 255 when
  Docker restarted mid-session and did not come back). Both are "not deploy blockers"
  by `docs/ops/deployment-guide.md`, which also excludes desktop/mobile Playwright and
  the backend integration suite from the release gate.
- Remaining risks or follow-ups:
  1. **Deploy pending** — `make release-check` (data lane needs the dev Postgres) and
     `make deploy` (buildx build/push + blue/green cutover) both need a working Docker
     daemon; every `docker` invocation was hanging at the end of this session.
  2. `make release-check` will re-run the whole backend unit lane and may reproduce the
     two environmental non-passes above; they are Docker/load artefacts, not code
     failures (the same suite passed 3618 tests).
  3. `1m`/`3m`/`6m` are 30/90/180 days, not calendar months.
  4. The conversion numerator keys on the contact, so a contact reachable on two
     channels counts once per conversation that captured evidence.
  5. `docs/archive/`, `docs/journals/`, `docs/troubleshooting/` and the design-QA
     audit keep their historical bot-run references — those are records of the state at
     the time, not current state.
