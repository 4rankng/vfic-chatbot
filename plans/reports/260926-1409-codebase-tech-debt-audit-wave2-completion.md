# Codebase Tech-Debt Audit Wave 2 — Completion

## Task record

- Task: Full codebase audit to identify tech debt; create tickets on the
  file-based kanban board (`kanban/`), generator-fed per `scripts/kanban/README.md`.
- Scope: read-only audit of the whole repo at HEAD `31d30377` (`main`); 9 parallel
  read-only lanes (backend architecture, backend correctness, backend perf/async,
  security, graph/bot, frontend, testing/CI, ops/deploy/deps, docs/hygiene);
  aggregation + dedupe; wave-2 ticket module `tickets_e.py` (49 cards, all `TODO`);
  minimal multi-wave extension of `scripts/kanban/build.py`; README origin section;
  this report. No product code, tests, docs-as-truth, or board columns were changed.
- Files changed: `scripts/kanban/tickets_e.py` (new, ticket data), 
  `scripts/kanban/build.py` (per-ticket `date`/`audit_head` + `tickets_e` import), 
  `scripts/kanban/README.md` (wave-2 origin), 49 new `kanban/TODO/*.md` (generated), 
  this report.
- Instructions retrieved: `AGENTS.md`, `skill://ak-code-review` (+ codebase-scan
  workflow), `skill://plans-kanban`, `scripts/kanban/README.md`,
  `docs/project-roadmap.md` (open K-items), `standards/agent-completion-checklist.md`,
  prior audit record `plans/reports/260921-1055-codebase-tech-debt-audit-completion.md`,
  wave-1 record `plans/reports/260924-2100-kanban-sweep-completion.md`.
- Approval required: No. No protected path edited (config/security/ratelimit,
  webhooks, auth_dependencies, bot policy, index.css, manifests, deployment files,
  Makefiles, alembic). `scripts/kanban/` and `kanban/` are not protected. Findings
  that WOULD need approval to fix are flagged on their cards (SEC-11 compose,
  TEST-19/TEST-22 CI, REL-11 ratelimit, ARCH-26 config, ARCH-27 bot surface,
  PERF-17 migration, FE-26 manifest).
- Approval evidence: N/A.

## Result

Board state after rebuild (`python3 scripts/kanban/build.py`):

- **TODO 49** (wave 2: ARCH 9 · REL 8 · FE 7 · OPS 7 · TEST 7 · DOC 5 · PERF 3 · SEC 3)
- IN_PROGRESS 0 · DEV_COMPLETED 2 · QA_TESTED 112 (wave-1 state preserved
  byte-identically — `git status` on those columns is empty)
- Board totals: P0 8 · P1 43 · P2 84 · P3 28 · closed 114/163

Highest-severity wave-2 cards: OPS-21 (`make backup` broken 100% by the IMAGE_TAG
guard collision; also blocks `deploy-backend`), OPS-25 (uncommitted 2026-09-26
incident remediation — CI green is void for it; commit-only action),
OPS-22 (post-flip verify + deploy-breaking lists omit worker-maintenance/
metrics-watch), REL-12 (LLM semaphore rebind bypasses the deployment-wide cap after
multi-tool rounds), REL-13 (progressive early bubble overwritten with reply='' on
lane failure), ARCH-20/ARCH-21 (graph/runner.py 2153 LOC, clients.py 1481 LOC with a
719-line method).

## Verification

Audit-time baseline at `31d30377` (all run first-hand this session):

- `ruff check .` (backend, venv) → "All checks passed!"
- `pytest -m "not integration"` → **2397 passed, 24 skipped, 137 deselected**
  (an initial `1 failed` in `test_deployment_makefile` was proven to be stale
  local `__pycache__` bytecode — a stale cpython-314 pyc sat beside the 3.12 one;
  after clearing `__pycache__` the module passes 39/39 and the full lane is green;
  CI on `main` is green at HEAD, run 36219117447)
- `tsc --noEmit --project tsconfig.app.json` → clean
- `eslint "**/*.{mjs,ts,tsx}" --no-warn-ignored` → clean

Generator verification:

- Idempotence before changes: rebuild at HEAD reproduced the 114 wave-1 cards with
  zero git diffs.
- Idempotence after the multi-wave refactor with an empty `tickets_e.TICKETS`:
  again zero diffs.
- Final build: `wrote 163 cards … TODO: 49, IN_PROGRESS: 0, DEV_COMPLETED: 2,
  QA_TESTED: 112`; card spot-check (OPS-21) renders correct frontmatter
  (`opened: 2026-09-26`), sections, and the wave-2 provenance footer (HEAD
  `31d30377`).
- Id uniqueness: build's duplicate-id assert passed across `tickets_a–e`.

## Known items deliberately NOT carded

- SEC-01 (unauthenticated Zalo OA webhook) — withdrawn/deferred by owner request;
  unchanged at HEAD.
- K-4, K-10, K-11, K-12 (docs/project-roadmap.md) — open owner decisions, unchanged.
- Sweep-ledger holds (droplet rehearsal, dependabot pip↔uv.lock shape, ops-alerts
  cron wiring, bundle-zip pruning, InvalidTag ownership, provenance drop, kb/pencil
  relocation, logging-credentials test) — unchanged; OPS-23/TEST-17/OPS-25 cover
  only their materially changed aspects.
- FE-02/FE-08 QA-blocked boundary edges — already tracked on their wave-1 cards.
- Uncommitted working tree (docs/incident-runbook.md edit, untracked
  turn_pipeline_check.py + 2 test files) — owner's in-flight incident work; OPS-25
  records the landing requirement without authorizing an agent commit.

## Out-of-scope repository change (not mine — flag for the owner)

Working tree at session start (preserved untouched): modified
`docs/incident-runbook.md`; untracked `backend/scripts/turn_pipeline_check.py`,
`backend/tests/test_turn_pipeline_check.py`,
`backend/tests/integration/test_turn_pipeline_check.py`,
`plans/reports/260926-1325-prod-bot-silence-recovery-completion.md`. These are the
2026-09-26 bot-silence remediation set — see OPS-25: committed deploy scripts and
docs already reference the untracked module, so landing it is urgent (carded, not
actioned).

During the audit a concurrent session kept expanding that set (final `git status`
also shows `backend/docker-compose.yml`, `backend/scripts/bg_deploy.sh`,
`backend/scripts/bg_rollback.sh`, `backend/tests/test_deployment_makefile.py`,
`docs/deployment-guide.md` modified). All owner-owned, preserved untouched. Wave-2
cards are anchored at audited HEAD `31d30377`; if the concurrent work lands, the
affected cards (OPS-21/22/25, TEST-16) may shrink — re-verify the cited lines
before picking them up.

## Completion gates

| Gate | Status | Evidence |
|---|---|---|
| Requested behavior or artifact is complete | PASS | 49 evidence-anchored cards in `kanban/TODO/` from a full-repo 9-lane audit; board rebuilt via the generator; counts above |
| Diff is limited to the approved scope | PASS | `git status`: `scripts/kanban/{build.py,tickets_e.py,README.md}`, 49 new `kanban/TODO/*.md`, this report; nothing else |
| Protected operations were avoided or approved | PASS | No protected path touched; audit itself read-only; gated fixes flagged on cards |
| Focused tests/checks pass | PASS | `build.py` run green with duplicate-id assert; card format spot-checked |
| Broader regression tests pass | PASS | Backend unit 2397 passed / 24 skipped; frontend tsc + eslint clean (baselines, audit is read-only) |
| Lint passes for affected code | PASS | `ruff check .` clean (covers scripts/kanban/*.py) |
| Type checking passes for affected code | PASS | N/A for Python data module (ruff-clean); frontend tsc clean (baseline) |
| Build/import validation passes | PASS | `python3 scripts/kanban/build.py` imports tickets_a–e and renders 163 cards |
| Security and privacy impact reviewed | PASS | No secrets/PII in cards; evidence cites code locations only; SEC lane produced 3 cards with bounded claims |
| Performance and async-I/O impact reviewed | PASS | No runtime changes; perf lane produced 3 cards with measured-cost evidence |
| Accessibility and Vietnamese UX reviewed for UI changes | N/A | No UI changed; FE cards preserve Vietnamese copy verbatim |
| Error handling and compatibility reviewed | PASS | Generator default (`date`/`audit_head` keys) keeps wave-1 rendering byte-identical — proven twice (empty module + final build) |
| Documentation impact handled | PASS | `scripts/kanban/README.md` origin section documents wave-2 provenance + baseline; board is the deliverable |
| No new unlinked `TODO`, `FIXME`, or `HACK` | PASS | None added |
| Final `git diff --check` passes | PASS | Clean |

## Remaining risks / follow-ups

- OPS-25 is the time-critical card: the incident guardrail exists only uncommitted.
- Wave-2 ids assume the board remains generator-fed; if a card moves column, edit
  `column=` in `tickets_e.py` (or add a COMPLETIONS entry) and rebuild — never
  hand-move files.
- Scouts had no shell, so churn-vs-923b1d3f was approximated from reflogs and hot
  paths; every claim is nonetheless anchored to `path:line` read at `31d30377`.
- No commit/push/branch/PR created (per repository workflow).
