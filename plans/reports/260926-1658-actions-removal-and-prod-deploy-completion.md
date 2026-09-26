# Agent Completion Checklist — GitHub Actions removal + production deploy

## Task record

- Task: commit all code, push, and deploy to production. Blocked mid-way by a CI
  billing block, so the operator then asked to remove GitHub Actions entirely
  ("I dont need, if need to deploy I just run make deploy") and to keep OpenWiki
  refreshed at the end of a task instead of on a schedule.
- Scope: delete both workflows, make `release-check` a purely local gate set, add
  a local `openwiki` target, correct every doc that claimed CI gated releases,
  then release the pending work (the per-project external API feature + the
  operator's deploy-hardening + kanban wave 2) to production blue/green.
- Files changed: `.github/workflows/{quality-gates,openwiki-update}.yml` (deleted),
  `Makefile`, `AGENTS.md`, `docs/{code-standards,testing,project-roadmap,deployment-guide}.md`,
  `frontend/registry.json`, plus this report.
- Instructions retrieved: `AGENTS.md`, `docs/deployment-guide.md` (read in full —
  required before any deploy), `docs/project-roadmap.md`, `frontend/scripts/check-registry-paths.mjs`,
  `backend/scripts/bg_deploy.sh`, `standards/agent-completion-checklist.md`.
- Approval required: yes — deploying, and changing deployment/Makefile files.
- Approval evidence: the operator's explicit instruction ("commit all code, push,
  and deploy to pord", then "remove github actions I dont need, if need to deploy
  I just run make deploy"; "openwiki update should be done at the end of each task
  not base on ci").

## Completion gates

| Gate | Status | Evidence (command and result, file reference, or N/A reason) |
|---|---|---|
| Requested behavior or artifact is complete | PASS | Workflows deleted (`.github/` now holds only `dependabot.yml`); `release-check` runs every lane locally with no `gh` reference (`make -n release-check \| grep -c "gh run"` → 0); `make openwiki` exists and is `.PHONY` (it would otherwise be shadowed by the `openwiki/` directory — verified: the target now runs and fails with an actionable message instead of "up to date"); the release is live in production. |
| Diff is limited to the approved scope | PASS | Every change serves the removal, the release gate, or the pending release. No unrelated file touched; the operator's previously-dirty WIP was committed earlier as its own reviewed commits, not rewritten. |
| Protected operations were avoided or approved | PASS | No secret, `.env`, dependency manifest, or `index.css` edit. The deploy was explicitly requested and executed through the sanctioned `make deploy` path. `docs/deployment-guide.md` §4's documented Alembic HEAD was updated to `0056` — required, because `release-check` asserts it matches `alembic heads`. |
| Focused tests/checks pass | PASS | `npm run registry:check` → "complete (254 files)". `make -n openwiki`, `make openwiki` (blocker path), `make -n release-check`, `make -n deploy` all parse and behave. |
| Broader regression tests pass when shared behavior changed | PASS | `make deploy` ran the full local gate set and every lane passed, in the deploy log: `ruff` clean; backend unit **2459 passed, 24 skipped**; integration **137 passed** (harness smoke 4 first as a canary, incl. `test_migration_roundtrip_walk`); frontend registry 254 files, unit **610 passed**, coverage gate above all four floors (statements 69.02/67, branches 58.56/55, functions 59.82/57, lines 71.25/68), build OK, Playwright desktop **4 passed** + mobile **4 passed**; golden RAG **54/54 = 100%**, `release gate passed`. |
| Lint passes for affected code | PASS | `ruff check .` → "All checks passed!"; `npm run lint` → clean. |
| Type checking passes for affected code | PASS | `npm run typecheck` → clean (run inside `release-check`). |
| Build/import validation passes for affected code | PASS | `npm run build` → built in 2.72s (inside `release-check`); both images built and pushed for `0d0fcab9`. |
| Security and privacy impact reviewed | PASS | Removing CI removes a third-party record of gate results, not a control: `release-check` still aborts on the first failure and `make deploy` cannot push an image before it passes. Production-side gates unchanged (`smoke_turn.py` before the Caddy flip, `turn_pipeline_check.py` after). No secret entered a workflow file or the repo. `both workflows used pinned action SHAs` — deleted, so the surface shrinks. Accepted trade-off recorded in roadmap K-13. |
| Performance and async-I/O impact reviewed | N/A | No application code path changed in this task; the deploy hardening shipped earlier is what alters worker choreography, and its own report covers it. |
| Accessibility and Vietnamese UX reviewed for UI changes | N/A | No UI change in this task. The shipped panel's UX was reviewed in the feature report. |
| Error handling and compatibility reviewed | PASS | Deleting `quality-gates.yml` cannot break a runtime path; `release-check` keeps every gate, so a failing lane still blocks the release. `docker compose ps` and `deploy-status` require `IMAGE_TAG` on the droplet (pre-existing quirk, unchanged) — every verification below passes it explicitly. |
| Documentation impact handled | PASS | `AGENTS.md` (OpenWiki step 7 + the marked block no longer claims a scheduler), `docs/code-standards.md` ("Gate notes"), `docs/testing.md` ("Root Quality Gates"), `docs/deployment-guide.md` §3, `docs/project-roadmap.md` K-8/K-12 + new K-13, `Makefile` comments. |
| No new unlinked `TODO`, `FIXME`, or `HACK` | PASS | None introduced. |
| Final `git diff --check` passes | PASS | Clean; `release-check` runs it as a gate. |
| Final `git status --short` reviewed | PASS | Clean at the moment `release-check` ran (a hard requirement of the gate). |

## Production verification (independent of the deploy script's own summary)

| Check | Result |
|---|---|
| Public edge | `https://bot.tingting.vip/health` → `{"status":"ok","env":"production"}` |
| Frontend root | `https://bot.tingting.vip/` → 200 |
| Active colour / tag | `ACTIVE_COLOR=blue`, `PREV=green@31d30377` (`make -C backend deploy-status`) |
| Running containers | 3× `worker-chatbot`, `worker-persistence`, `worker-maintenance`, `worker-ingest`, `worker-followup`, `scheduler`, **`metrics-watch`** (created for the first time), `web-blue`, `frontend` — all `tinghire-be:0d0fcab9` / `tinghire-fe:0d0fcab9` |
| Alembic revision | `alembic current` → `0056_project_external_api (head)`; `alembic_version` → `0056_project_external_api` |
| New column | `projects.external_api` → `jsonb`, nullable |
| Turn-pipeline gate | `PIPELINE OK: consumers live, no conversation awaiting a reply, outbox drained`; `live consumers {'webhook_high': 3, 'recovery': 3, ...}`; queue depths all 0 |
| New admin route is live | `GET /api/v1/knowledge/projects/<uuid>/external-api` → **401** (registered, auth required) while a control unknown sibling path → **404** |
| Panel is in the shipped bundle | `ProjectEdit-<hash>.js` in the prod frontend contains `API ngoài của dự án` and `Tải tệp lên` |
| Capability assumption resolved | `installation_state` 0 rows, `installation_manifest_revisions` 0 rows → no active manifest policy, so the legacy `_agent_turn` path runs. That is the path that receives the `=== API NGOÀI CỦA DỰ ÁN ===` block, and `TOOL_SCHEMAS` is bound unfiltered, so `call_project_api` is reachable. The plan's `job_advisory` contingency cannot trigger. `projects` has 2 active rows. |

## Result

- Overall status: PASS
- Release: 6 commits pushed to `main` (`37d81784`, `e30f3163`, `ee415318`, `fb556cbc`, `e7010b22`, `0d0fcab9`); production cut over to `web-blue` at `0d0fcab9`, with `make rollback` restoring `green@31d30377` in ~1s.
- Remaining risks or follow-ups:
  - **OpenWiki refresh could not run.** `make openwiki` is wired and refuses with a clear message, but there is no usable `OPENROUTER_API_KEY`: `backend/.env` has it empty and the shell exports only `SILVERSEA_OPENROUTER_API_KEY` (a different product's key — not reused on the operator's behalf). Fill `backend/.env` or `export OPENROUTER_API_KEY=...` and run `make openwiki`. Until then the index is stale by whatever has landed since it was last generated.
  - **No CI history.** A release now has no third-party record that the gates passed (K-13). `kanban/QA_TESTED/*` cards that cite `.github/workflows/quality-gates.yml:NN` are historical audit records and were deliberately left untouched.
  - `chore(ci)` note: `frontend/registry.json` drift is now caught by `release-check` (it was CI-only before this task, which is how the gap surfaced). `.github/dependabot.yml` was left in place — it is not a workflow, and dependency alerts are advisory.
  - The first push in this task legitimately failed the CI gate (`Registry paths`), which is the one thing the removed workflow caught and the local gate now covers.
