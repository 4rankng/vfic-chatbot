# Agent Completion Checklist

## Task record

- Task: (1) remove the operator-facing context-window field and pin the chatbot
  context window; (2) fix the Zalo OA App ID copy-button layout; (3) style the
  Facebook OAuth session input; (4) fix the `webhook → nhận việc` pickup latency;
  then commit, push, and deploy to production — including the tech debt found
  while doing it.
- Scope:
  - Worker reliability: record turns that die to a crash or the RQ job timeout;
    back off delivery-failure recovery retries.
  - Queue topology: recovered turns move to a low-priority `recovery` queue;
    `worker-chatbot` scales to 3 replicas.
  - Knowledge capacity: every chatbot agent runs the fixed 1M window.
  - Settings UI: context-window field removed end to end; field actions stay on
    the input row; the OAuth session input uses the shared styling.
  - Debt: `make seed` repaired for the persona/contact schema; release gate no
    longer evaluates synthetic seed telemetry; deploy scripts derive replica
    counts from compose instead of hardcoding them; dev worker consumes
    `recovery`; ops docs and NFR table updated.
  - Excluded: bot prompts/personas, Alembic revisions, security controls,
    `backend/app/core/config.py` policy values (flagged, not changed).
- Files changed (4 commits):
  - `e0cd975f` — chatbot_worker, reconcile_worker, knowledge_base_capacity,
    integration_settings, schemas/integrations, main, docker-compose, seed_dev,
    frontend api/Zalo/Facebook/settings.css, worker + capacity tests, inventory
    fixture/digest, docs.
  - `08aa1db4` — slo_service, release_gate, seed_dev (synthetic marker), gate
    tests, backend/Makefile, docs.
  - `37af4c68` — bg_deploy.sh, bg_rollback.sh (derived replica counts).
  - `c7b227e6` — deployment-script contract tests.
- Instructions retrieved: `AGENTS.md`, `plans/260922-0945-custom-context-window`,
  `docs/deployment-guide.md`, `docs/qa-runbook.md`, `standards/*`.
- Approval required: deployment + Makefile edits + the 1M-window scope change —
  all explicitly requested by the operator ("fix all issues you find including
  tech debt, then commit push and deploy to prod").
- Approval evidence: the operator's instructions in this session.

## Diagnosis evidence (production, read-only)

- `bot_runs` per day: 09-12 → 6 runs (pickup p50 28 ms), 09-13 → 8 (37 ms),
  09-22 → 89 (p50 30 072 ms / p95 100 518 ms).
- Every 09-22 run with pickup > 2 s is `execution_source = recovery`, clustered
  01:15:42–01:18:23 UTC: 62 runs / 62 distinct conversations (57 SUPPRESSED,
  4 SENT, 1 ERROR); their inbound messages dated 09-21 14:23–23:49. Live turns
  at 13:08–13:17 measured 10–147 ms.
- `bot_runs` for 09-14…09-21: zero rows while inbound traffic continued — the
  outage was invisible because died turns recorded nothing.
- Redis counters: `reconcile_re_enqueues_total = 300 049`,
  `reconcile_stale_lock_broken = 298 091`, `reconcile_skipped_locked_total`
  unset — against 352 lifetime runs.
- Local probe (RQ 2.10.0, `UnixSignalDeathPenalty`): a job that catches
  `BaseException` swallows `JobTimeoutException` and RQ records it `finished`
  (failed registry empty); the same job without the catch is `failed`.

## Deployment incident and repair (2026-09-22 ~14:00 UTC)

- First `make deploy` failed **after** the Caddy flip: `bg_deploy.sh` and
  `bg_rollback.sh` hardcoded `require_running_service_count "worker-chatbot" 2`,
  so the new 3-replica topology failed post-flip verification; the automatic
  rollback then failed its own verification with the same literal and reported
  "operator intervention required", leaving `ACTIVE_COLOR=blue` while Caddy still
  routed to `web-green`.
- Blast radius: no downtime (public `/health` 200 throughout; Caddy stayed on the
  old color) and no data impact. Workers ran the old image with the new command.
- Repair: fixed both scripts to read `deploy.replicas` from
  `docker compose config --format json` (failing only when fewer containers run
  than declared, falling back to 1 when the count is unreadable), updated the two
  contract tests that pinned the literal, flipped Caddy onto the already
  smoke-tested `web-blue`, then re-ran the full deploy.

## Completion gates

| Gate | Status | Evidence |
|---|---|---|
| Requested behavior or artifact is complete | PASS | All four fixes shipped and live (see deploy verification); field gone end to end; `make seed` runs twice cleanly |
| Diff is limited to the approved scope | PASS | 4 commits, no prompt/persona/alembic/security changes; `config.py` untouched |
| Protected operations were avoided or approved | PASS | Makefile + compose edits were explicitly requested; no secret file touched |
| Focused tests/checks pass | PASS | capacity 11, reconcile 12, abandonment 5, enqueue utils 6, gate/slo 58, deployment-script 32 |
| Broader regression tests pass when shared behavior changed | PASS | `pytest -m "not integration"` → 2221 passed, 42 skipped; integration smoke → 4 passed; `npm run test:unit:app -- --run` → 107 files / 569 tests |
| Lint passes for affected code | PASS | `ruff check .` clean; `eslint` clean on changed TSX |
| Type checking passes for affected code | PASS | `npm run typecheck` clean |
| Build/import validation passes for affected code | PASS | Release gate built the frontend + backend image and pushed both at `c7b227e6` |
| Security and privacy impact reviewed | PASS | Failure rows store reason text only (no message content/secrets); no new PII logging; no auth/CORS/webhook changes |
| Performance and async-I/O impact reviewed | PASS | Removes the reconcile hot loop and the OpenRouter metadata call; recovery work no longer competes with live turns; +1 worker ≈ 130 MB of the droplet's ~670 MB free |
| Accessibility and Vietnamese UX reviewed for UI changes | PASS | Action buttons keep ≥36 px (44 px ≤479 px) and their `aria-label`s; removed field only; new copy is Vietnamese |
| Error handling and compatibility reviewed | PASS | Abandoned-turn recording is best-effort and never raises; removed API field rejects with 422 only for a client that still sends it (none exists); stale DB row is inert |
| Documentation impact handled | PASS | deployment-guide, database, system-architecture, codebase-summary, project-overview-pdr, standards/performance updated |
| No new unlinked `TODO`, `FIXME`, or `HACK` | PASS | None added |
| Final `git diff --check` passes | PASS | clean before each commit |
| Final `git status --short` reviewed | PASS | only intended files, all committed and pushed |

## Production verification (after deploy, tag `c7b227e6`)

- `ACTIVE_COLOR=green`, `PREV_COLOR=blue`, `PREV_TAG=08aa1db4`; Caddyfile routes
  `web-green` (5 refs) — state files and routing agree; `web-blue` stopped and
  retained for `make rollback`.
- Containers: `web-green`, `worker-chatbot-1..3`, `worker-persistence`,
  `worker-ingest`, `worker-followup`, `scheduler`, `frontend` all
  `ghcr.io/4rankng/tinghire-*:c7b227e6`, healthy.
- RQ: three workers advertise `queues=webhook_high,recovery` (strict priority),
  all queues depth 0, `/health/queue` → `total_workers: 6`.
- Deployed image code: `backoff 900`, `enqueue_recovery_chat_run` present,
  `window 1024000`.
- Public edge: `/health` 200 (`{"status":"ok","env":"production"}`), `/` 200.
- Frontend bundle: `ZaloIntegrationPage-DwHqRJZH.js` contains 0 hits for
  "Cửa sổ ngữ cảnh" and 1 hit for `settings-field-has-action`; the integrations
  CSS chunk contains the same class.
- Smoke gate: real turn on the new color before the flip (14:08/14:10 UTC rows,
  pickup 95/123 ms), and the deploy proceeded past it to the flip.

## Result

- Overall status: PASS — deployed and verified.
- Remaining risks or follow-ups:
  1. `reconcile_max_age_seconds = 86400` still lets the sweep recover day-old
     unanswered conversations (now throttled by the 900 s backoff and off the
     live queue). Lowering it is a one-line change in the protected
     `backend/app/core/config.py` — awaiting the operator's call.
  2. Production runs `c7b227e6`; HEAD after this record is docs-only.
  3. The first deploy attempt's rollback left `web-blue` running the earlier
     `08aa1db4` build; it is the current rollback target (`PREV_TAG`), which is
     the intended blue/green state.
