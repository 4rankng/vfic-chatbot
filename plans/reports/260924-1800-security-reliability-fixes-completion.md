# Agent Completion Checklist

## Task record

- Task: Fix every defect the tech-debt board's **Security** and **Reliability** cards describe, correct the board artifact itself, and move the board to the house kanban layout.
- Scope: 14 cards (SEC-02…SEC-08, REL-01…REL-07); `kanban/` + `scripts/kanban/` board structure and data; operator docs for the new knobs. Out of scope: the PERF/FE/ARCH/TEST/OPS/DOC cards (a parallel session works those), deployment, and QA_TESTED promotion.
- Files changed: 15 slices, 23 commits on `main` (`ee0e28e5` → `55b3b3bb`). Backend: `api/{leads,bot_runs,auth,webhooks,knowledge,personas,conversations,jobs,integrations}.py`, `core/{security,config,ratelimit}.py`, `shared/infrastructure/rate_limits.py` (new), `identity/infrastructure/http.py`, `services/{user_service,password_reset_service,integration_settings,zalo_bot_service,outbox_service,knowledge/service}.py`, `services/lead/{service,repository}.py`, `services/ingestion/limits.py`, `services/conversation/{bot_path,repository}.py`, `services/dashboard/service.py`, `workers/{reconcile_worker,chatbot_worker}.py`, `graph/{clients,usage,llm_semaphore,runner,semantic_cache}.py`, `graph/tools/knowledge.py`, `recruitment/infrastructure/service_adapters.py`, `main.py`, `Caddyfile.template`. Frontend: `providers/rest/authProvider.ts`. Board: `scripts/kanban/{build.py,tickets_a.py,tickets_b.py,README.md}` + `kanban/<COLUMN>/` cards. Docs: `docs/deployment-guide.md`, `backend/.env.example`.
- Instructions retrieved: `AGENTS.md` (auto-loaded), `docs/testing.md` (lanes), `standards/agent-completion-checklist.md`, the 14 card files.
- Approval required: yes — AGENTS.md gates auth/JWT/CORS/rate-limit/webhook/security-control and deployment-template changes.
- Approval evidence: the user selected "Fix the product bugs those tickets describe" (whose description named the AGENTS.md gate for SEC-03/04/06/07/08) together with the board options, then instructed "fix all issues and commit frequently every logical change". No deploy, branch, merge or push was performed; no migration, `.env` or secret file was touched.

## Completion gates

| Gate | Status | Evidence |
|---|---|---|
| Requested behavior or artifact is complete | PASS | 14/14 cards implemented; board restructured to the house layout with `kanban/` = four column folders and `scripts/kanban/` = generator+data; SEC-01 withdrawal recorded; columns/evidence logs on the finished cards. |
| Diff is limited to the approved scope | PASS | `git log --oneline ee0e28e5^..55b3b3bb` — each commit is one card or one board change; files outside the 14 cards were touched only where the cards name them (`api/bot_runs.py`, `api/jobs.py`, `api/conversations.py`, `services/knowledge/service.py`, `config.py`, `Caddyfile.template`). |
| Protected operations were avoided or approved | PASS | Approval recorded above. `.env` untouched; `alembic/versions/**` untouched; no deploy/`make` target run. |
| Focused tests/checks pass | PASS | Per slice: leads 77 passed; turn delivery 204 passed; REL-02/07 65 passed; integrations+headers 130 passed; auth 62 + 16 passed. All new files listed in the card evidence logs. |
| Broader regression tests pass when shared behavior changed | PASS (with attributed external failures) | `backend/.venv/bin/pytest -m "not integration"`: **2463 passed, 42 skipped, 2 failed**. Both failures are `test_architecture_boundaries.py` frontend-only checks (new edges + browser globals in `projects/application/*`, `conversations/presentation/*`, `providers/rest/dataProvider`) created by the parallel session's uncommitted frontend work — not by this change set. Frontend unit lane: 548 passed, 5 failed in 10 files (6 fail to collect), all in that same refactor surface; `authProvider.ts` is the only file this change set touched there. |
| Lint passes for affected code | PASS | `backend/.venv/bin/ruff check .` → "All checks passed!". |
| Type checking passes for affected code | PASS | `npm run typecheck` (tsc --noEmit) → clean. |
| Build/import validation passes for affected code | PASS | `python3 scripts/kanban/build.py` run twice → byte-identical output, 112 cards in 4 columns; backend modules import; `git diff --check` clean. |
| Security and privacy impact reviewed | PASS | IDOR closed (404 not 403), logout/rotation added, JWT aud/iss/required-claims + algorithm allowlist, secret previews reduced to configured+length with step-up reveal, CSP/XFO/Permissions-Policy + Host allowlist, upload/webhook body ceilings, route rate limits. No secret, PII or message content added to logs; the reveal audit row records the actor, not the value. |
| Performance and async-I/O impact reviewed | PASS | Blocking Redis removed from the LLM telemetry, semaphore release, dashboard reads and the per-turn queue-depth read; the semantic-cache scan and decode moved off the loop; the new limiter is one Redis INCR per protected request. |
| Accessibility and Vietnamese UX reviewed for UI changes | PASS (N/A for layout) | Only user-visible strings added: the rate-limit and step-up messages are Vietnamese, matching the existing copy. No markup or visual change; the admin secret field keeps the `preview` name it already rendered. |
| Error handling and compatibility reviewed | PASS | 404 on out-of-scope ids; 413 on oversized payloads; 429 with distinct fail-open/fail-closed messages; the limiter is a no-op in development; `/leads/{id}/assign` now 400s on an unknown recruiter; admins keep unrestricted results; no response schema removed. |
| Documentation impact handled | PASS | `docs/deployment-guide.md` knob table + `backend/.env.example` carry `ALLOWED_HOSTS`, `JWT_ISSUER`/`JWT_AUDIENCE`, `RATELIMIT_*`; `scripts/kanban/README.md` documents the layout, the withdrawn SEC-01 and the deferred Zalo OA webhook. |
| No new unlinked `TODO`, `FIXME`, or `HACK` | PASS | `grep -rn "TODO\|FIXME\|HACK" backend/app` shows no additions from this change set. |
| Final `git diff --check` passes | PASS | Clean at `55b3b3bb`. |
| Final `git status --short` reviewed | PASS | Only the parallel session's files remain dirty; nothing of this change set is left uncommitted. |

## Result

- Overall status: PASS (all 14 cards' fixes committed and evidenced; board follows the house layout).
- Remaining risks or follow-ups:
  1. **Not QA_TESTED.** The unit lanes are green, but the integration lane (`pytest -m integration` against Postgres, including the two new files `test_reconcile_superseded_inbound.py` and `test_inline_claim_outbox_visibility.py`) and the e2e lane were not run, so the cards sit in DEV_COMPLETED.
  2. **SEC-06 residual by design.** JWTs still live in `localStorage`; the card's suggested fix does not require moving to httpOnly cookies. CSP is scoped to the sources the console actually uses — re-verify `style-src`/`img-src` in a browser before relying on the header as a control.
  3. **SEC-03 residual.** Logout bumps `token_version` (the card's "cheapest correct fix"); a per-user refresh *generation* store was not added, so a replayed stolen refresh token still works until the next revocation.
  4. **Two frontend gate failures + 5 frontend test failures come from the parallel session** working the FE/PERF cards in this same tree; they are not caused by this change set and were left untouched.
  5. **Cross-session integrity.** Their status marks were restored from HEAD after a rebuild reset them, and both `_build.py` and the new `build.py` now make `column` data-driven so a rebuild cannot lose progress again.
