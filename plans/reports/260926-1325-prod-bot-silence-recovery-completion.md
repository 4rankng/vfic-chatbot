# Prod bot-silence recovery + deploy-gap fixes + droplet cleanup — completion

## Task record

- Task: User reported the production bot not answering (Zalo Messenger + web
  inbox), asked to fix it now, then approved fixing every issue found and
  cleaning up unused material on the prod server to release resources.
- Scope: production diagnosis and recovery; the deploy-time defect that caused
  it; the related drift/broken-observability defects found while doing so; and
  resource cleanup. No application/business-logic change.
- Files changed:
  - `backend/scripts/bg_deploy.sh` — `WORKERS` now includes
    `worker-maintenance` + `metrics-watch`; added `TURN_WORKERS` with
    `rolling_recreate_service` (one-replica-at-a-time roll); pre-flip
    live-consumer gate; post-flip turn-pipeline gate.
  - `backend/scripts/bg_rollback.sh` — same `WORKERS` list, rolling turn-worker
    recreate, same pipeline gate (helpers duplicated on purpose: the rollback
    script is the emergency path and must not depend on a sibling file).
  - `backend/scripts/turn_pipeline_check.py` (new) — post-flip gate asserting the
    bot is *answering*, with a `--min-consumers` self-test.
  - `backend/docker-compose.yml` — web healthcheck budgets (probe socket 3s→10s,
    compose timeout 5s→15s, interval 5s→10s); `worker-chatbot` `start_period`
    60s→180s; `metrics-watch` sends an allowed `Host` header.
  - `backend/tests/test_deployment_makefile.py` — added the invariants that would
    have caught both drifts; updated one literal command expectation to the new
    mechanism.
  - `backend/tests/test_turn_pipeline_check.py` (new), and
    `backend/tests/integration/test_turn_pipeline_check.py` (new).
  - `docs/incident-runbook.md`, `docs/deployment-guide.md` — new incident class,
    implemented mitigations, Postgres password-rotation procedure, deploy steps.
  - This report.
  - NOT mine: `scripts/kanban/build.py` is modified in the working tree by the
    user/another session and was left untouched.
- Instructions retrieved: `AGENTS.md`, `docs/incident-runbook.md`,
  `docs/deployment-guide.md`, `backend/app/services/installation/lifecycle.py`,
  `backend/app/api/webhooks.py`, `backend/app/models/{conversation,outbox}.py`.
- Approval required: yes, in two parts. The user explicitly approved fixing all
  found issues and the prod cleanup ("approve, fix all issues you find").
  **Not executed:** the Postgres password rotation — `AGENTS.md` makes editing
  secrets (`.env`, credentials) a hard boundary, so the procedure is documented
  and its replacement logic verified instead of run. See Remaining risks.
- Approval evidence: conversation record of this session.

## Incident summary (root cause)

A blue/green deploy of commit `31d30377` (ordered by a peer session at 12:46
local) ran in **two waves** (web-blue up 05:04:36 UTC; `bg_deploy.sh` started
05:10, green + workers 05:12:41 UTC). `worker-chatbot` is a single stack-wide
service keyed to `${IMAGE_TAG}` (3 replicas), **not** per color, so each wave
recreated all chatbot workers; its preload took **83.2 s** and the first replica
registered on `webhook_high` at 05:15:26. Inbound turns arriving in that window
were accepted (HTTP 200, "Received" in Zalo) and produced no reply until a
worker registered.

Blackout for conversation `859d328d`: last pre-gap reply 05:12:35, inbound
05:13:02 / 05:13:57 / 05:15:51 / 05:15:56, replies 05:18:37 and 05:19:14.
Screenshot times 13:13/13:15 local = 05:13/05:15 UTC (host is UTC+8; verified).

**No message was lost.** All 13 `outbound_outbox` rows created in the 30 minutes
around the gap are `SENT` with `attempts = 1`, and every conversation with
inbound activity in the following 3 h has a BOT reply after its last inbound
(23/23 `ok`, zero `NO_REPLY`).

### Ruled out (not the cause)

`webhook accepted while runtime inactive channel=bot|facebook` is the legacy ack
path: `InstallationService.resolve_active()` returns `None` when
`installation_state` is empty, and the turn is still enqueued with an empty
runtime stamp. Prod's installation tables all have 0 rows and
`pg_stat_user_tables.n_tup_ins = 0` — they were never populated there, so this
line logs for every inbound message for the life of the database, including
while the bot was answering.

## Issues found and fixed (all in this session)

1. **Deploy turn gap** (the reported outage). Fixed by rolling `worker-chatbot`
   one replica at a time (`up -d --no-recreate --scale`, which creates the
   missing replica and leaves survivors untouched), plus a pre-flip gate
   requiring a live consumer and a post-flip pipeline gate.
2. **`worker-maintenance` drift.** Pinned to `${IMAGE_TAG}` in compose but absent
   from `WORKERS`, so the outbound dispatcher (queue `maintenance` — the
   component that actually pushes bot replies to Zalo) had been running
   38-hour-old code. Added to both scripts and recreated in prod.
3. **`metrics-watch` never deployed.** The queue-depth/saturation alert poller —
   the exact signal that would have flagged this incident — was pinned to
   `${IMAGE_TAG}` and referenced by nothing, so it had never been created in
   production. Added to `WORKERS` and started.
4. **`metrics-watch` broken by construction.** On its first-ever run it reported
   `web_down: neither web colour answered /health`: `TrustedHostMiddleware`
   (SEC-06) answers **400** to a direct `Host: web-green:8000` probe. It now
   sends an allowed `Host` header (env-tunable `METRICS_WATCH_HOST_HEADER`).
5. **False `unhealthy` under load.** Both web colors reported
   `Health check exceeded timeout (5s)` during deploy-time CPU contention (probe
   socket timeout was 3s inside a 5s compose timeout), which can abort a deploy
   mid-flip. Raised to 10s/15s with a 10s interval; `worker-chatbot`
   `start_period` 60s→180s to match the measured 83.2 s preload.
6. **No gate could see a stall.** `/health/queue` proves workers *exist*, not
   that work *drains*. Added `scripts/turn_pipeline_check.py` (details below).
7. **Resource waste.** 413 images (13.98 GB) with only 9 in use; one dead job
   container. Pruned → **11.22 GB reclaimed**, disk 44%→22%.

## Added gate: `scripts/turn_pipeline_check.py`

Fails when the pipeline is stalled, not merely when a process is down:

- fewer than `--min-consumers` (default 1) live RQ workers registered on
  `webhook_high`;
- a `BOT`-mode conversation whose newest inbound in `--window` (default 300 s)
  has no reply after it — in-flight turns are excluded via an open `bot_runs`
  row, and `HUMAN`/`CLOSED` conversations are excluded because the bot is silent
  there by design;
- a `PENDING` outbound row older than `--stale-after` (default 120 s).

Self-test: `--min-consumers 999` MUST exit 1. Wired into both deploy scripts'
post-flip verification (a failure rolls the deploy back).

## Completion gates

| Gate | Status | Evidence (command and result, file reference, or N/A reason) |
|---|---|---|
| Requested behavior or artifact is complete | PASS | Bot answering: `SMOKE OK: outcome='sent'` (4 runs, incl. after every change); `PIPELINE OK: consumers live, no conversation awaiting a reply, outbox drained`; live outbox `SENT` rows. Fixes: `WORKERS` drift closed for both scripts, rolling roll implemented, pipeline gate added, healthcheck budgets corrected, `metrics-watch` created and probing 200. Cleanup: `Total reclaimed space: 11.22GB`, `df -h /` 21G→11G used. |
| Diff is limited to the approved scope | PASS | `git status --short`: the 7 modified + 3 new files above are exactly the deploy/gate/compose/docs/tests surface. `scripts/kanban/build.py` is a pre-existing user change, untouched. |
| Protected operations were avoided or approved | PASS (with one deliberate stop) | No alembic migration, auth/JWT/CORS/rate-limit, prompt/persona, dependency, or Makefile change. `.env`, Postgres/Redis volumes, and the `web-blue` rollback container untouched. Prod actions were the user's approved cleanup/fix mandate: `worker-maintenance` and `metrics-watch` recreated from the compose's own `${IMAGE_TAG}` pin, one dead container removed, images pruned. **Postgres password rotation NOT performed** — `AGENTS.md` forbids editing secrets; procedure documented in `docs/incident-runbook.md` instead. |
| Focused tests/checks pass | PASS | `pytest tests/test_deployment_makefile.py tests/test_turn_pipeline_check.py` → 47 passed. `pytest -m integration tests/integration/test_turn_pipeline_check.py` → 6 passed. `ruff check .` → All checks passed. `bash -n` on both deploy scripts → OK. `docker compose config -q` → valid. |
| Broader regression tests pass when shared behavior changed | PASS | Full fast suite: `pytest -m "not integration"` → **2397 passed, 24 skipped**. Full integration suite: `pytest -m integration` → **137 passed, 2421 deselected** (2m02s), including the 6 new pipeline-gate integration tests. |
| Lint passes for affected code | PASS | `.venv/bin/ruff check .` → `All checks passed!` (backend, whole tree). |
| Type checking passes for affected code | N/A | Backend has no type-check gate wired (ruff only). |
| Build/import validation passes for affected code | PASS | New gate imports cleanly under the test venv and ran inside the prod container (`python - < script`) against live Redis+Postgres; `docker compose config` parses the edited compose; scripts pass `bash -n`. No image was rebuilt (`IMAGE_TAG` unchanged). |
| Security and privacy impact reviewed | PASS (with follow-up) | The `Host`-header fix keeps SEC-06 intact (no widening of `allowed_hosts`) — the probe presents an already-allowed host. No secrets written to disk or logged; DB password redacted in outputs. Follow-up: the prod `POSTGRES_PASSWORD` was unavoidably echoed into this session's transcript by `DATABASE_URL` during credential discovery — rotate it (procedure documented). Postgres is docker-internal only, not host-exposed. |
| Performance and async-I/O impact reviewed | PASS | Root cause is CPU/memory contention on a 1.9 GiB / 2-vCPU host: 83.2 s worker preload, health probes exceeding 5 s. `metrics-watch` costs ~128 M cap (stdlib poll loop, read-only `/health`, `/metrics`, `/health/queue`). Post-change `free -m` available 382 M→672 M; disk 38 G free. The rolling roll trades a longer deploy for a gap-free one. |
| Accessibility and Vietnamese UX reviewed for UI changes | N/A | No UI change. User-visible impact was delayed Vietnamese bot replies; no message loss. |
| Error handling and compatibility reviewed | PASS | Pipeline gate fails *closed*: an unreadable RQ registry yields no consumer counts and therefore fails, rather than reporting a healthy pipeline it cannot observe (pinned by a unit test). Both deploy scripts keep their pre-existing abort semantics; the new gate runs post-flip so a stall rolls back instead of shipping silently. Mixed worker tags during a roll are compatible (blue/green already runs both versions concurrently; migrations are additive before step 4). |
| Documentation impact handled | PASS | `docs/incident-runbook.md`: new dated incident class with detect queries + benign signals + implemented mitigations, plus a copy-pasteable Postgres password-rotation procedure. `docs/deployment-guide.md`: deploy step 4 (rolling vs blunt recreate, the `WORKERS` rule), step 8 (pipeline gate, corrected replica counts incl. `worker-maintenance`). |
| No new unlinked `TODO`, `FIXME`, or `HACK` | PASS | None added. |
| Final `git diff --check` passes | PASS | Clean (no whitespace errors). |
| Final `git status --short` reviewed | PASS | See "Diff is limited" above. |

## Result

- Overall status: PASS for everything executed in this session. The bot is
  verified answering, the deploy-time defect is fixed and pinned by tests, the
  three drift/broken-observability defects are closed, and 11.22 GB was freed.
- Remaining risks or follow-ups:
  1. **Postgres password rotation not executed** (boundary: never edit secrets).
     Procedure + verification steps in `docs/incident-runbook.md`; the
     replacement logic was proven on synthetic data (3/3 occurrences incl. both
     URLs, unrelated lines intact). Needs an explicit go-ahead from the operator.
  2. **The fix takes effect on the next image build.** `bg_deploy.sh` /
     `bg_rollback.sh` are shipped by `scp` and are already live on the droplet,
     but the post-flip gate invokes `python -m scripts.turn_pipeline_check`
     *inside the container*, so it requires an image built from this commit.
     Until then the gate would fail-closed on a deploy — which is the intended
     direction (abort rather than ship a stalled pipeline), but it means the next
     deploy must be built from this commit.
  3. **Workers are still restarted on every deploy** — the roll removes the gap
     but not the restart. Per-color worker services would remove it entirely;
     that is a larger topology change and was deliberately not attempted.
  4. Host memory is still tight (1.9 GiB, 14 containers). Pruning freed disk,
     not RAM; trimming `worker-chatbot` replicas is a deploy change needing
     approval.
  5. A redeploy of an unchanged sha still restarts everything — check
     `/opt/vfic/ACTIVE_COLOR` + `PREV_TAG` and `docker ps` before assuming the
     bot is broken.
