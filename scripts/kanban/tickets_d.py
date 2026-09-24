"""Ops/deploy/data + docs/repo-hygiene tickets.

Sources: /tmp/audit/AuditDepsOps.md (C1-C4, H1-H6, M1-M9, L1-L5) and
/tmp/audit/AuditHygiene.md (F1-F18). Severities, line citations and caveats are
carried over from those reports verbatim; nothing here was re-derived.
"""

TICKETS = [
    # ---------------------------------------------------------------- CRITICAL
    dict(
        id="OPS-01",
        column="QA_TESTED",
        title="Full-droplet backup dies on a non-existent Caddyfile, and restore hard-requires the artifact it can never produce",
        sev="critical",
        area="ops",
        labels=["ops", "reliability"],
        effort="S",
        evidence_log=[
            'Landed: backup-droplet.sh snapshots via guarded snapshot_file() and fetches the RENDERED /opt/vfic/Caddyfile (dies if empty/unflipped); restore accepts Caddyfile or Caddyfile.template',
            'BLOCKED: the card requires an end-to-end run against a throwaway droplet + a date in docs/DROPLET-BACKUP-RESTORE.md — no droplet access from here',
            'verified: bash -n on both scripts',
            'QA 2026-09-24 (orchestrator, first-hand): unit 2299 passed + ruff clean; integration 130 passed (Postgres 16 disposable DB, alembic head); frontend tsc/eslint/vitest 593 green; e2e chromium 4 and Mobile Chrome 4 green against the real backend',
        ],
        problem=(
            "`make backup-full` copies `backend/Caddyfile` into the bundle at step 4 of 7, but that "
            "file does not exist — only `backend/Caddyfile.template` is tracked, and the production "
            "Caddyfile is generated on the droplet by `flip_caddy.sh`. Because the script runs under "
            "`set -euo pipefail`, the run aborts after the DB dump and the volume tarballs but before "
            "`zip`/`.zip.sha256`, so no artifact the runbook recognises is ever produced. "
            "`make restore-prod` then aborts at preflight on the very member the backup can never emit."
        ),
        evidence=[
            "`scripts/backup-droplet.sh:78` — `cp \"$REPO_ROOT/backend/Caddyfile\" \"$BUNDLE/config-snapshot/Caddyfile\"`, inside a script that sets `set -euo pipefail` at `:22`; no `backend/Caddyfile` exists, only `backend/Caddyfile.template`.",
            "`scripts/restore-droplet.sh:42` — `[ -f \"$BUNDLE/config-snapshot/Caddyfile\" ] || { echo \"missing …\"; exit 2; }`; `:80` uploads it as `/opt/vfic/Caddyfile`.",
            "`docs/DROPLET-BACKUP-RESTORE.md:27` — lists `config-snapshot/Caddyfile` as a required bundle member.",
            "`scripts/backup-droplet.sh:120-124` — `zip` and the `.zip.sha256` checksum run *after* the failing step, so a partially populated `backups/<ts>/` directory is all the operator gets.",
            "`backend/scripts/flip_caddy.sh:32-36` — the real production Caddyfile is *generated* on the droplet; `Makefile:134-136` (`backup-full`) and `Makefile:140` (`restore-prod`) are the entry points.",
        ],
        impact=(
            "The entire \"delete the droplet, rebuild it later\" disaster-recovery story is "
            "non-functional: `make backup-full` cannot emit a zip and `make restore-prod` cannot start "
            "even with a hand-built bundle. [INFERENCE] The pair has never been exercised — no restore "
            "rehearsal exists anywhere in `docs/`, `openwiki/` or `plans/` — though the missing "
            "`backend/Caddyfile` proves it cannot have succeeded recently."
        ),
        fix=(
            "Capture the *rendered* `/opt/vfic/Caddyfile` from the droplet (it is the real edge config "
            "and contains the active colour) with one `scp` beside the existing `.env` fetch, keeping "
            "`Caddyfile.template` as a second snapshot; wrap the three `cp` calls at "
            "`scripts/backup-droplet.sh:77-79` in existence guards that `die` with a clear message; and "
            "make `scripts/restore-droplet.sh` accept either `Caddyfile` or `Caddyfile.template` and "
            "regenerate via `flip_caddy.sh`. Then run the pair end-to-end against a throwaway droplet "
            "and record the date in `docs/DROPLET-BACKUP-RESTORE.md`."
        ),
        notes=(
            "Merge with OPS-02 — both are defects in the same backup/restore pair, and the end-to-end "
            "rehearsal should close both at once."
        ),
    ),
    dict(
        id="OPS-02",
        column="QA_TESTED",
        title="Restore pins production to the latest tag instead of the dump's recorded image tag and never verifies schema compatibility",
        sev="critical",
        area="ops",
        labels=["ops", "reliability"],
        effort="M",
        evidence_log=[
            'Landed: restore-droplet.sh resolves IMAGE_TAG from ACTIVE_COLOR then manifests/docker-images.txt and fails closed when neither exists',
            'REMAINING: the deploy side (fail closed in bg_deploy.sh/flip_caddy.sh when ACTIVE_COLOR tag != running container tag) is not done',
            'QA 2026-09-24 (orchestrator, first-hand): unit 2299 passed + ruff clean; integration 130 passed (Postgres 16 disposable DB, alembic head); frontend tsc/eslint/vitest 593 green; e2e chromium 4 and Mobile Chrome 4 green against the real backend',
        ],
        problem=(
            "`scripts/restore-droplet.sh` runs `docker compose pull` and `docker compose up -d` with "
            "`IMAGE_TAG` unset, so compose resolves `${IMAGE_TAG:-latest}` — the tag that is re-pushed "
            "on every deploy, not the tag that produced the dump. The bundle *does* record the running "
            "images in `manifests/docker-images.txt`, but nothing reads it. The script also skips "
            "`alembic upgrade head` on the grounds that \"the dump already has schema@head\" and never "
            "checks that the restored `alembic_version` matches the revision the pulled image expects."
        ),
        evidence=[
            "`scripts/restore-droplet.sh:88` (`docker compose pull`) and `:132` (`docker compose up -d`) — neither exports `IMAGE_TAG`, so compose falls back to `${IMAGE_TAG:-latest}` at `backend/docker-compose.yml:44, 131, 147, 168, 195, 213, 84`.",
            "`scripts/backup-droplet.sh:88-89` — writes `manifests/docker-images.txt` into the bundle; no reader for it exists anywhere in `scripts/`.",
            "`scripts/restore-droplet.sh:8-12` — explicitly skips `alembic upgrade head` (\"the dump already has schema@head\") with no assertion against the image's expected head.",
            "`backend/Makefile:100` and `frontend/Makefile:70` — `latest` is re-pushed on every deploy, so \"restore a backup from 3 weeks ago\" means new code against old schema.",
            "`web-blue`/`web-green` carry no `IMAGE_TAG` default guard, so a bare `docker compose up -d` on the droplet (reboot, manual fix, `backend/scripts/flip_caddy.sh:38`) silently drifts off the tag recorded in `/opt/vfic/ACTIVE_COLOR`.",
        ],
        impact=(
            "A restored production can run code newer or older than the dumped schema, producing exactly "
            "the failure modes the blue/green flow exists to prevent: mid-turn `UndefinedColumn` errors, "
            "wrong enum semantics, or a bot that boots healthy and crashes on the first write."
        ),
        fix=(
            "Have `scripts/restore-droplet.sh` read the tag from `manifests/docker-images.txt` (falling "
            "back to an explicit `--tag`), export `IMAGE_TAG` for every `docker compose pull`/`up` "
            "invocation, then run `python -m scripts.widen_alembic_version && alembic upgrade head` and "
            "assert `alembic current` equals the image's head before declaring success. Also fail closed "
            "on the droplet when `ACTIVE_COLOR`'s tag differs from the running container's image tag."
        ),
        notes="Merge with OPS-10 — the same missing `IMAGE_TAG` guard is what lets the restore pull `latest`.",
    ),
    dict(
        id="OPS-03",
        column="QA_TESTED",
        title="The primary make backup path omits the key that encrypts integration credentials, so a restore silently yields undecryptable data",
        sev="critical",
        area="ops",
        labels=["ops", "security"],
        effort="S",
        evidence_log=[
            '29446018 — make backup pulls /opt/vfic/.env + warns when the encryption key is absent',
            '4825c714/1f6b6fd9 — jwt_secret fallback labelled a migration hazard; DR-lost-secret documented',
            'verified: make -n backup parses; grep proves the key check sits on the fetch path',
            'QA 2026-09-24 (orchestrator, first-hand): unit 2299 passed + ruff clean; integration 130 passed (Postgres 16 disposable DB, alembic head); frontend tsc/eslint/vitest 593 green; e2e chromium 4 and Mobile Chrome 4 green against the real backend',
        ],
        problem=(
            "`make backup` dumps only `pg_dump` of `vfic` to OneDrive — no `.env` — yet every "
            "`integration_settings` row is sealed with AES-GCM under a key derived from "
            "`INTEGRATION_SETTINGS_ENCRYPTION_KEY` (with `JWT_SECRET` as fallback), and that key existed "
            "only in `/opt/vfic/.env`. On `InvalidTag` the service skips the row with a warning and "
            "callers fall back to env values, so a restore looks successful while silently discarding "
            "credentials."
        ),
        evidence=[
            "`backend/app/services/integration_settings.py:273-275` — `raw = self._settings.integration_settings_encryption_key or self._settings.jwt_secret; self._key = hashlib.sha256(raw.encode()).digest()`; sealing/opening at `:277-291` and `:293-306`.",
            "`backend/app/services/integration_settings.py:392-402` — on `InvalidTag` the row is skipped with a warning and callers fall back to env values; `:1140-1148` fails closed only for context-bound Page tokens.",
            "`Makefile:77-95` — `make backup` writes just the `pg_dump` to OneDrive; this is the documented primary backup (`docs/deployment-guide.md:359`) and a hard dependency of `deploy-backend` (`Makefile:54`).",
            "`Makefile:98-131` — `make restore` loads that dump into the **dev** DB, whose `.env` carries the dev `JWT_SECRET` (`.env.example:30`) and an empty `INTEGRATION_SETTINGS_ENCRYPTION_KEY` (`prod-env.sh:61`): a different key by construction.",
            "`docs/DROPLET-BACKUP-RESTORE.md:110-118` — discusses Postgres-password consistency across a restore but never mentions this key.",
        ],
        impact=(
            "Two distinct data-loss paths. (1) `make restore` into dev: every `integration_settings` row "
            "(Zalo bot token + webhook secret, MiniMax/OpenRouter keys, Facebook App secret/Page tokens) "
            "becomes `InvalidTag`, is logged as `integration setting decrypt failed … falling back to "
            "env`, and is discarded — the restore reports success. (2) If the droplet is lost and only "
            "the OneDrive dumps survive, production's sealed credentials are unrecoverable, because "
            "`INTEGRATION_SETTINGS_ENCRYPTION_KEY` (and the `JWT_SECRET` fallback) lived only in "
            "`/opt/vfic/.env`."
        ),
        fix=(
            "Treat `/opt/vfic/.env` as part of every backup — add it to `make backup` (`Makefile:77-95`), "
            "as `make backup-full` already does; document `INTEGRATION_SETTINGS_ENCRYPTION_KEY` as the "
            "DR-lost-secret and store it in a password manager separate from the droplet; add a "
            "post-restore assertion that decrypts one known integration row and fails loudly on "
            "`InvalidTag` instead of warning; and label the `jwt_secret` fallback at "
            "`backend/app/services/integration_settings.py:273-275` as a migration hazard, since rotating "
            "`JWT_SECRET` re-breaks every stored secret."
        ),
        notes="Merge with OPS-01/OPS-02 — all three live in the same backup/restore path and should be rehearsed together.",
    ),
    dict(
        id="OPS-04",
        column="QA_TESTED",
        title="No log rotation anywhere and no disk monitoring, so disk-full is an unalerted total outage",
        sev="critical",
        area="ops",
        labels=["ops", "reliability"],
        effort="S",
        evidence_log=[
            '4825c714 — x-logging anchor attached to all 14 services (10 MB x 3 per container)',
            'scripts/ops-alerts.sh — disk >80/>95%, reclaimable Docker, /metrics thresholds, /health',
            'verified: yaml.safe_load parses; docker compose config -q clean with env set; bash -n',
            'QA 2026-09-24 (orchestrator, first-hand): unit 2299 passed + ruff clean; integration 130 passed (Postgres 16 disposable DB, alembic head); frontend tsc/eslint/vitest 593 green; e2e chromium 4 and Mobile Chrome 4 green against the real backend',
        ],
        problem=(
            "`backend/docker-compose.yml` declares no `logging:`, `max-size` or `max-file` keys on any of "
            "its 12 services, and there is no `daemon.json` in the repo, so Docker's default `json-file` "
            "driver grows without bound. Structured JSON logging to stdout is the *only* observability, "
            "by design, and nothing monitors host disk."
        ),
        evidence=[
            "`backend/docker-compose.yml` — zero `logging:`/`max-size`/`max-file` keys across all 12 services; a grep over the whole file returns only `healthcheck` hits, and no `daemon.json` exists in the repo.",
            "`backend/app/core/logging.py:63-73` — structured JSON logging to stdout is the only observability path, by design (`docs/deployment-guide.md:444-446`).",
            "Unbounded log producers: 3× `worker-chatbot`, `worker-ingest`, `worker-followup`, `scheduler`, both web colours, `caddy` (access logs) and `postgres` (`backend/docker-compose.yml`).",
            "`worker-ingest` runs with a 3600s job timeout (`INGEST_JOB_TIMEOUT_SECONDS`) whose reconcile and LLM warning volume is unbounded (`backend/docker-compose.yml`).",
        ],
        impact=(
            "When the volume fills, Postgres cannot write WAL and the whole stack goes down — with no "
            "alert, because per OPS-06 nothing pages a human. Detection time for disk-full today is "
            "**unbounded**: a human has to run `df`."
        ),
        fix=(
            "Add a compose `x-logging` anchor (`driver: json-file`, `max-size: 10m`, `max-file: 3`) and "
            "attach it to every service in `backend/docker-compose.yml` — one change, immediate bound. "
            "Add a host cron that alerts on `df` > 80% and on `docker system df`."
        ),
        notes="Merge with OPS-06 — the disk-full row of its detection table is this ticket.",
    ),
    # -------------------------------------------------------------------- HIGH
    dict(
        id="OPS-05",
        column="QA_TESTED",
        title="Production and CI both ignore uv.lock, and 29 of 30 backend dependencies have no upper bound",
        sev="high",
        area="ops",
        labels=["ops", "reliability"],
        effort="M",
        evidence_log=[
            'QA 2026-09-24 (orchestrator, first-hand): unit 2299 passed + ruff clean; integration 130 passed (Postgres 16 disposable DB, alembic head); frontend tsc/eslint/vitest 593 green; e2e chromium 4 and Mobile Chrome 4 green against the real backend',
        ],
        problem=(
            "`backend/Dockerfile` installs with `pip install -e .` and every CI job uses "
            "`pip install -e .[dev]`; neither consults `backend/uv.lock`, which has no consumer anywhere "
            "in the repo. Only one of the 30 declared backend dependencies carries a cap, so the image "
            "that reaches production is whatever PyPI served at build time."
        ),
        evidence=[
            "`backend/Dockerfile:18` — `pip install --upgrade pip && pip install -e .` (no `[dev]`, which is good; no lock, which is not).",
            "`.github/workflows/quality-gates.yml` — all four backend/frontend jobs run `pip install -e .[dev]` (backend-unit, backend-integration, functional-e2e, release-gate), and the pip cache is keyed on `backend/pyproject.toml`, never on `uv.lock`.",
            "`backend/uv.lock` — 435 KB / 2468 lines with resolution markers for 3.12/3.13/3.14, but grepping `uv sync|uv lock|--frozen|uv.lock` across `backend/`, `Makefile` and `.github/` returns no consumer.",
            "`backend/pyproject.toml:6-34` — only `redis>=5.2,<8.0.0` (`:20`) is capped; `fastapi`, `sqlalchemy`, `alembic`, `pydantic`, `langchain-core`, `langchain-openai`, `langgraph`, `httpx` and `rq` are open-ended.",
            "There is no image-build job in `.github/workflows/quality-gates.yml`, so CI never builds or runs the image it ships.",
        ],
        impact=(
            "A fresh upstream major (SQLAlchemy 3, FastAPI 1, LangChain 1, Pydantic 3) can land in "
            "production without a single code review or CI signal, and `uv.lock` provides a false sense "
            "of pinning. The same commit can also build into two different environments, so deploy-time "
            "breakage is not reproducible."
        ),
        fix=(
            "Pick one story and enforce it: either `uv export --frozen --no-dev -o requirements.txt` in "
            "`backend/Dockerfile` plus `uv sync --frozen` in CI (keeping `uv lock --check` in "
            "`release-check`), or delete `uv.lock` and add explicit `<N+1` caps to every entry in "
            "`backend/pyproject.toml:6-34`. Either way, add an image-build + `/health` + `smoke_turn` job "
            "to CI so pin drift is caught before the droplet sees it."
        ),
        notes="Merge with OPS-20 (`release-check` never checks lockfile consistency) and OPS-14 (a lockfile that resolves two copies of one package).",
    ),
    dict(
        id="OPS-06",
        column="QA_TESTED",
        title="Nothing scrapes the metrics endpoints and there are no alerts, so the only signal is the reconcile worker",
        sev="high",
        area="ops",
        labels=["ops", "reliability"],
        effort="M",
        evidence_log=[
            '4825c714 + 1f6b6fd9 — scripts/ops-alerts.sh wired as a 1-minute cron, thresholds documented',
            'verified: bash -n scripts/ops-alerts.sh; thresholds match CHAT_QUEUE_MAX_DEPTH semantics',
            'remainder: an EXTERNAL uptime check still needs a third party — cannot be added from the repo',
            'QA 2026-09-24 (orchestrator, first-hand): unit 2299 passed + ruff clean; integration 130 passed (Postgres 16 disposable DB, alembic head); frontend tsc/eslint/vitest 593 green; e2e chromium 4 and Mobile Chrome 4 green against the real backend',
        ],
        problem=(
            "`/metrics` and `/health/queue` exist and export queue depths, worker counts and 9 reconcile "
            "counters, but Caddy does not proxy them and no scraper, uptime check or alert rule exists "
            "anywhere in the repo. Nothing in the system pages a human, so most failure classes are only "
            "noticed if someone happens to open the admin console."
        ),
        evidence=[
            "`backend/app/main.py:209-211` (`/health`), `:214-245` (`/metrics`: RQ queue depths + worker count + reconcile counters), `:247-257` (`/health/queue` via `backend/app/core/ops_health.py:12`); the 9 counters are defined at `backend/workers/reconcile_worker.py:27-36`.",
            "`backend/Caddyfile.template:17-50` — routes only `/webhooks/*`, `/health`, `/api/*`, `/realtime/*` and `/socket.io/*`; `/metrics` and `/health/queue` are not proxied, and `docs/deployment-guide.md:437-439` acknowledges they are internal-only.",
            "`docs/deployment-guide.md:444-446` — \"**No external APM**. No Sentry/Datadog/OpenTelemetry.\" No scrape config, uptime check or alert rule exists in the repo.",
            "`backend/scripts/bg_deploy.sh:120-135` — the only consumer asserts queue-health keys *exist* at deploy time; nothing watches them afterwards.",
        ],
        impact=(
            "Nothing in the system pages a human. Detection times today:\n\n"
            "| Failure | Detected by | Time to human awareness |\n"
            "|---|---|---|\n"
            "| Bot turn silently lost | `reconcile_worker` re-enqueues on the `recovery` queue, ~60s scan + 120s grace (`backend/workers/reconcile_worker.py:9-12`); no counter is alerted | recovery ~3-4 min, **notification: never** |\n"
            "| Queue-depth growth / worker saturation | `/metrics`, `/health/queue` (chart only, shown via `api/dashboard.py`) | only if a human opens the console |\n"
            "| DB connection exhaustion | pool timeout raises → 500s in logs | never proactively |\n"
            "| LLM provider outage | provider failover + suppressed-turn log (`docs/deployment-guide.md:311-312`) | never proactively |\n"
            "| Disk full | nothing | unbounded (OPS-04) |\n"
            "| Wedged worker process | **not detected at all** (OPS-08) | never |"
        ),
        fix=(
            "(a) An external uptime check on `https://bot.tingting.vip/health` with email/Telegram "
            "alerting; (b) a 1-minute cron on the droplet (or a GitHub Action) that curls `/metrics` and "
            "`/health/queue` inside the Docker network — `docker compose exec -T web-$(cat ACTIVE_COLOR) "
            "python -c …`, the pattern already documented at `docs/deployment-guide.md:333-336` — and "
            "alerts on `queue_depth > CHAT_QUEUE_MAX_DEPTH*0.5`, `busy_workers == total_workers` for N "
            "minutes, rising `reconcile_enqueue_failed_total`/`reconcile_unknown_send_outcome`, and disk "
            "> 80%; (c) expose `/metrics` through Caddy behind an allowlist only if a scraper needs it."
        ),
        notes="Merge with OPS-04 (disk alert) and OPS-08 (wedged-worker signal).",
    ),
    dict(
        id="OPS-07",
        column="QA_TESTED",
        title="Blue/green deploy runs migrations with no pre-migration dump and no lock_timeout",
        sev="high",
        area="ops",
        labels=["ops", "reliability"],
        effort="S",
        evidence_log=[
            'QA 2026-09-24 (orchestrator, first-hand): unit 2299 passed + ruff clean; integration 130 passed (Postgres 16 disposable DB, alembic head); frontend tsc/eslint/vitest 593 green; e2e chromium 4 and Mobile Chrome 4 green against the real backend',
        ],
        problem=(
            "`bg_deploy.sh` step 3 runs `alembic upgrade head` before the new colour boots, with no "
            "`pg_dump` immediately prior and no `lock_timeout`/`statement_timeout` on the migration "
            "connection. The only nearby backup is the OneDrive dump taken by `deploy-backend`, which "
            "plain `make deploy` does not run. The 240s health budget covers the web colour, not the "
            "migration step."
        ),
        evidence=[
            "`backend/scripts/bg_deploy.sh` step 3 — `docker compose run --rm --no-deps web-blue sh -c 'python -m scripts.widen_alembic_version && alembic upgrade head'`, with no dump immediately before it.",
            "`Makefile:54` — `deploy-backend` runs `release-check` + `backup`; `Makefile:37` — plain `make deploy` does not, so the closest dump can be days old.",
            "`backend/alembic/env.py:46-49` and `backend/alembic.ini` — set no `lock_timeout`/`statement_timeout`.",
            "`backend/scripts/bg_deploy.sh:170` — the 240s health budget covers the web colour only, not the migration step.",
            "`backend/alembic/versions/0017_replace_lead_stage_flow.py:48-51` — documents that `QUALIFIED`/`APPLIED`/`HIRED` collapsed irrecoverably into `REGISTERED` on upgrade, so its only rollback is a dump.",
        ],
        impact=(
            "(1) If a migration is destructive in one direction, the only rollback is a dump that may be "
            "days old. (2) A DDL lock queued behind a long-running query waits forever — `ALTER TYPE` and "
            "`ALTER COLUMN TYPE` need ACCESS EXCLUSIVE and nothing bounds the wait, so the deploy hangs "
            "indefinitely while Caddy still serves the old colour: no user-visible outage, but no progress "
            "and no timeout."
        ),
        fix=(
            "Add `pg_dump` to `backend/scripts/bg_deploy.sh` immediately before the migration step, keep "
            "the last N dumps, and set `lock_timeout=5s` plus a `statement_timeout` for the migration "
            "connection in `backend/alembic/env.py`. On lock timeout, fail the deploy loudly and leave the "
            "old colour serving."
        ),
        notes="Merge with OPS-17 — the missing `lock_timeout` is what makes non-concurrent index DDL a deploy-stalling risk.",
    ),
    dict(
        id="OPS-08",
        column="QA_TESTED",
        title="Worker healthchecks only ping Redis, so a wedged worker reports healthy forever",
        sev="high",
        area="ops",
        labels=["ops", "reliability"],
        effort="M",
        evidence_log=[
            'QA 2026-09-24 (orchestrator, first-hand): unit 2299 passed + ruff clean; integration 130 passed (Postgres 16 disposable DB, alembic head); frontend tsc/eslint/vitest 593 green; e2e chromium 4 and Mobile Chrome 4 green against the real backend',
        ],
        problem=(
            "Every worker and scheduler healthcheck is a Redis `ping()`. That proves the Redis client "
            "works, not that the worker consumes its queue, so a worker whose work loop has hung stays "
            "`healthy`, is never recycled by `restart: unless-stopped`, and passes the deploy's service "
            "count assertion."
        ),
        evidence=[
            "`backend/docker-compose.yml:101,140,160,178` — every worker/scheduler healthcheck is `python -c \"import os,redis; redis.from_url(os.environ['REDIS_URL'], …).ping()\"`.",
            "`backend/docker-compose.yml:84-96` — `worker-chatbot` runs at `replicas: 3`.",
            "`backend/scripts/bg_deploy.sh:96-118` — `require_running_service_count` passes a wedged-but-healthy worker; `:120-135` already asserts `total_workers >= 5`, so the RQ registry primitive is available.",
            "`backend/workers/reconcile_worker.py:9-12` — the only recovery path, re-enqueuing lost turns on the `recovery` queue after a ~60s scan plus 120s grace.",
        ],
        impact=(
            "A worker that has lost its work loop (thread hung, Redis connection fine, queue silently "
            "backing up) is `healthy` forever, so candidate turns queue or get reconciled late (~3-4 min) "
            "with no operator signal — the exact failure the 2026-09-22 recoveries were about."
        ),
        fix=(
            "Make the worker healthcheck assert liveness of the loop, not the socket: write a heartbeat "
            "key from the worker's main loop (or use RQ's worker registry) and have the healthcheck assert "
            "`Worker.all(connection=…)` includes this hostname with a fresh heartbeat timestamp."
        ),
        notes="Merge with OPS-06 — this is the \"wedged worker\" row of its detection table.",
    ),
    dict(
        id="OPS-09",
        column="QA_TESTED",
        title="Memory limits cover 3 of 12 services and the documented host size contradicts itself",
        sev="high",
        area="ops",
        labels=["ops", "reliability"],
        effort="S",
        evidence_log=[
            'QA 2026-09-24 (orchestrator, first-hand): unit 2299 passed + ruff clean; integration 130 passed (Postgres 16 disposable DB, alembic head); frontend tsc/eslint/vitest 593 green; e2e chromium 4 and Mobile Chrome 4 green against the real backend',
        ],
        problem=(
            "Only `worker-chatbot`, `worker-persistence` and `oa-profile-backfill` declare "
            "`deploy.resources.limits.memory`; the other nine services — including `postgres`, "
            "`worker-ingest`, both web colours and `caddy` — are unbounded. Host RAM is documented as "
            "4 GB in two places but as 2 GB and 1.9 GiB in two others."
        ),
        evidence=[
            "`backend/docker-compose.yml:86-97` (`worker-chatbot`, 512M × `replicas: 3`), `:118-121` (`worker-persistence`, 512M), `:212-217` (`oa-profile-backfill`, 512M) — the only three limits; `web-blue`, `web-green`, `postgres`, `worker-ingest`, `worker-followup`, `scheduler`, `frontend`, `caddy` and `adminer` have none.",
            "`TECH.md:94` and `docs/deployment-guide.md:4` say **4 GB**; `backend/docker-compose.yml:92-96` says \"the **2GB** droplet … host headroom verified at deploy time\"; `backend/Dockerfile:25-28` says \"the **1.9GiB** host\".",
            "`backend/docker-compose.yml:8` tunes only `max_connections=150`, not memory, and `postgres` declares no `shm_size`, leaving `/dev/shm` at Docker's 64 MB default; `redis` is bounded only by `--maxmemory 256mb` (`:21`).",
            "`backend/scripts/bg_deploy.sh:120-135` verifies container counts but never that limits were applied. [INFERENCE] Docker Compose v2 honouring `deploy.replicas`/`deploy.resources.limits` is assumed — the repo's own tests and `declared_replicas` depend on it — and the limits were not verified at runtime.",
        ],
        impact=(
            "Declared caps sum to ≈2.0 GB; add PostgreSQL's default `shared_buffers` (~25% of RAM) plus "
            "`worker-ingest` embedding bursts and the resident non-limited services and the box is "
            "oversubscribed. A single runaway `worker-ingest` can trigger the OOM killer against Postgres "
            "or Caddy — an unbounded-blast-radius outage — and `max_connections=150` with a 64 MB "
            "`/dev/shm` invites the classic \"could not resize shared memory segment\" errors."
        ),
        fix=(
            "Set an explicit limit on every service in `backend/docker-compose.yml` with a documented sum "
            "that fits the real host size; fix the 4 GB / 2 GB / 1.9 GiB contradiction in one place; add "
            "`shm_size: 256mb` to `postgres`; and make `backend/scripts/bg_deploy.sh` verify "
            "`docker inspect .HostConfig.Memory` rather than only container counts."
        ),
        notes="Merge with OPS-10 — both are single-pass fixes to the same compose file.",
    ),
    dict(
        id="OPS-10",
        column="QA_TESTED",
        title="Every image is a mutable tag and no digest is pinned anywhere",
        sev="high",
        area="ops",
        labels=["ops", "reliability"],
        effort="S",
        evidence_log=[
            'QA 2026-09-24 (orchestrator, first-hand): unit 2299 passed + ruff clean; integration 130 passed (Postgres 16 disposable DB, alembic head); frontend tsc/eslint/vitest 593 green; e2e chromium 4 and Mobile Chrome 4 green against the real backend',
        ],
        problem=(
            "All base images and all eight application services resolve through mutable tags, and the "
            "restore path pulls `latest` by default. No digest pin exists in either Dockerfile or in "
            "compose, so an unattended pull can change the runtime under a frozen application version."
        ),
        evidence=[
            "`backend/docker-compose.yml:7` `pgvector/pgvector:pg16`, `:19` `redis:7-alpine`, `:224` `adminer:4`, `:235` `caddy:2`; `frontend/Dockerfile:5,13` `node:22-alpine` + `nginx:1.27-alpine`; `backend/Dockerfile:2` `python:3.12-slim`.",
            "`backend/docker-compose.yml:34,59,84,131,147,168,195,213` — all 8 application services use `${IMAGE_TAG:-latest}`.",
            "`scripts/restore-droplet.sh:88` — the restore path is exactly the unattended pull that can change the runtime under a frozen application version (see OPS-02).",
        ],
        impact=(
            "An unattended pull can silently change the runtime under a frozen application version, and "
            "base-image CVEs cannot be patched predictably because there is no periodic rebuild or pin "
            "cadence."
        ),
        fix=(
            "Pin base images by digest in `backend/docker-compose.yml`, `frontend/Dockerfile` and "
            "`backend/Dockerfile`; make `IMAGE_TAG` a required variable (`${IMAGE_TAG:?}`) so no code path "
            "can silently resolve `latest`; add a scheduled Dependabot/Renovate PR for the digests."
        ),
        notes="Merge with OPS-02 — the same missing `IMAGE_TAG` guard.",
    ),
    dict(
        id="OPS-11",
        column="QA_TESTED",
        title="Declared-but-unused dependencies and a dead curl in the runtime image",
        sev="medium",
        area="ops",
        labels=["ops", "tech-debt"],
        effort="S",
        evidence_log=[
            'QA 2026-09-24 (orchestrator, first-hand): unit 2299 passed + ruff clean; integration 130 passed (Postgres 16 disposable DB, alembic head); frontend tsc/eslint/vitest 593 green; e2e chromium 4 and Mobile Chrome 4 green against the real backend',
        ],
        problem=(
            "Five declared backend dependencies have no import anywhere in `backend/app`, "
            "`backend/scripts` or `backend/tests`, and `curl` is installed in the runtime image \"for "
            "healthcheck\" although every compose healthcheck uses Python's `urllib.request`."
        ),
        evidence=[
            "`backend/pyproject.toml:6-34` — `langgraph` has zero imports (`TECH.md:36` confirms \"manual node topology, not the LangGraph engine\"); `sse-starlette` has zero `sse_starlette`/`EventSourceResponse` imports, the SSE channel having been replaced by Socket.IO (`backend/app/services/realtime.py:5-7`, `backend/app/realtime/socketio.py:58-63`).",
            "`google-api-python-client` and `google-auth-oauthlib` — zero `googleapiclient`/`google.oauth2`/`Flow.` imports; only `google-genai` is used, via `from google import genai` (`backend/app/graph/clients.py:561`).",
            "`pgvector` (the Python package) — no `from pgvector…` import; vector columns are raw SQL and `backend/app/models/knowledge.py:308-310` stores `embedding` as `Text` (\"vector(3072) at DB; only written via raw SQL\").",
            "`backend/Dockerfile:10` installs `curl` for a healthcheck that does not use it — every compose healthcheck is `python -c urllib.request` (`backend/docker-compose.yml:51,69,101`).",
            "`backend/Caddyfile.template:34-38` — the `/realtime/*` handler is the only vestige of the removed SSE path.",
        ],
        impact=(
            "A larger image (curl plus four unused SDKs, including `google-api-python-client`'s large "
            "transitive tree), a larger attack surface, and four more unpinned packages that can break a "
            "build for no benefit. `sse-starlette` and `langgraph` also mislead readers of "
            "`backend/pyproject.toml` about the architecture."
        ),
        fix=(
            "Delete `langgraph`, `sse-starlette`, `google-api-python-client`, `google-auth-oauthlib` and "
            "`pgvector` from `backend/pyproject.toml:6-34`, and drop `curl` from `backend/Dockerfile:10`; "
            "remove the `/realtime/*` route from `backend/Caddyfile.template:34-38` if it is truly dead. "
            "Verify that `python-socketio`'s requirements still supply the Redis manager bits the realtime "
            "layer relies on."
        ),
        notes=(
            "The report's dependency-risk table also flags frontend devDeps (`daisyui`, `tldts`, `glob`, "
            "`pgsql-ast-parser`) as unused, but marks them **needs verification** (import greps only; "
            "configs and Vite plugins were not traced) — verify before deleting. The undeclared `locust` "
            "loadtest dependency is likewise a table row, not a numbered finding."
        ),
    ),
    dict(
        id="OPS-12",
        column="QA_TESTED",
        title="Documentation contradicts the code on operator-critical knobs",
        sev="medium",
        area="ops",
        labels=["ops", "documentation"],
        effort="S",
        evidence_log=[
            '1f6b6fd9 — LLM_CONCURRENCY_LIMIT 0→8, EMBED_CONCURRENCY_LIMIT 0→6, VARCHAR(32)→VARCHAR(128) note',
            'c37ef6a5 — qa-runbook seeding path corrected to backend/scripts/seed_dev.py',
            'verified: each value read back from backend/app/core/config.py and the widen script',
            'QA 2026-09-24 (orchestrator, first-hand): unit 2299 passed + ruff clean; integration 130 passed (Postgres 16 disposable DB, alembic head); frontend tsc/eslint/vitest 593 green; e2e chromium 4 and Mobile Chrome 4 green against the real backend',
        ],
        problem=(
            "Six documented facts that operators act on are wrong: LLM/embed throttling defaults, the JWT "
            "library, the uvicorn worker count, the alembic head, the DB-pool sizing model and whether "
            "`make dev` seeds. One runbook also documents a `VARCHAR(32)` revision limit that the code "
            "has already widened."
        ),
        evidence=[
            "`docs/deployment-guide.md` (\"Scaling knobs\") says `LLM_CONCURRENCY_LIMIT` and `EMBED_CONCURRENCY_LIMIT` default to **0 (disabled)**; the code has `llm_concurrency_limit: int = 8` (`backend/app/core/config.py:321`) and `embed_concurrency_limit: int = 6` (`:327`), i.e. the Redis semaphores are **on**.",
            "`TECH.md:40` says auth is \"**python-jose** JWT\" and `backend/tests/test_security.py:81` says \"jose must reject it\"; `backend/app/core/security.py:13-24` documents the deliberate PyJWT migration (python-jose's `ecdsa` / CVE-2024-23342) and imports `jwt` at `:23`.",
            "`TECH.md:10` claims \"Uvicorn `[standard]` … **2 workers** to use both vCPUs\" and `prod-env.sh:95` ships `WEB_CONCURRENCY=2`; `backend/Dockerfile:31` pins `\"--workers\", \"1\"` and nothing in the image entrypoint reads that variable.",
            "`TECH.md:24` and `docs/deployment-guide.md:281` say head is `0053_single_page_external_source_sync_state`; the single head is `0054_channel_account_projects` (`backend/alembic/versions/0054_channel_account_projects.py:41`).",
            "`backend/app/core/config.py:56-58` and `.env.example:17-19` size the DB pool for \"2 web + 6 chatbot replicas … ~13 processes\" while compose runs one active web plus `replicas: 3` (`backend/docker-compose.yml:85`); `docs/qa-runbook.md:31-32` claims `make dev` seeds the DB, but seeding is the separate `make seed` (`Makefile:67-69`); `docs/deployment-guide.md:296-300` insists revision IDs stay ≤32 chars while `0053_single_page_external_source_sync_state` is 41 and `backend/alembic/versions/0001_baseline.py:39-47` widens the column to 128.",
        ],
        impact=(
            "Operators tune LLM throttling on a false premise (\"semaphores are off\" when a turn is capped "
            "at 8 concurrent LLM calls and 6 embeds), incident responders follow the docs to a library "
            "that is not installed, and capacity math uses a topology that no longer exists."
        ),
        fix=(
            "Correct the six claims in `TECH.md`, `docs/deployment-guide.md` and `docs/qa-runbook.md`; "
            "better, generate the knob table from `backend/app/core/config.py` defaults with a small "
            "script so it cannot drift, and add a CI check asserting `docs/deployment-guide.md`'s HEAD "
            "string equals `alembic heads`."
        ),
        notes=(
            "Merge with DOC-03 — same drift class, but this ticket is limited to operator-critical knobs. "
            "The seeding claim is also part of OPS-18, and the `VARCHAR(32)` claim is part of OPS-20."
        ),
    ),
    dict(
        id="OPS-13",
        column="QA_TESTED",
        title="Dev venv is Python 3.14 while production and CI are 3.12",
        sev="medium",
        area="ops",
        labels=["ops", "testing"],
        effort="S",
        evidence_log=[
            'QA 2026-09-24 (orchestrator, first-hand): unit 2299 passed + ruff clean; integration 130 passed (Postgres 16 disposable DB, alembic head); frontend tsc/eslint/vitest 593 green; e2e chromium 4 and Mobile Chrome 4 green against the real backend',
        ],
        problem=(
            "The local virtualenv resolves to Python 3.14 while the image and both CI jobs pin 3.12, and "
            "`requires-python` has no upper bound. The Makefile's `dev`/`db` targets and `release-check` "
            "therefore exercise an interpreter no deployed artefact uses."
        ),
        evidence=[
            "`backend/.venv/lib/python3.14/site-packages/` and `__pycache__/*.cpython-314.pyc` throughout `backend/alembic/versions/`, `backend/scripts/` and `backend/app/`, versus `backend/Dockerfile:2` `FROM python:3.12-slim` and `python-version: \"3.12\"` in both CI jobs (`.github/workflows/quality-gates.yml`).",
            "`backend/pyproject.toml:4` — `requires-python = \">=3.12\"` with no upper bound; `backend/uv.lock:3-7` carries resolution markers for `<3.13`, `3.13.*` and `>=3.14`.",
            "`backend/pyproject.toml:62-64` — the `passlib` `crypt` filter exists precisely because of the 3.12→3.13 stdlib removal, so the version boundary is already load-bearing.",
            "Concrete bytecode evidence: `backend/alembic/versions/__pycache__/0054_channel_account_projects.cpython-314.pyc`, `backend/app/graph/__pycache__/runner.cpython-314.pyc`, against `[tool.ruff] target-version = \"py312\"`.",
        ],
        impact=(
            "Stdlib removals, C-extension differences (`asyncpg`, `cryptography`) and build behaviour mean "
            "bugs that reproduce in production can be invisible locally and vice versa; the interpreter "
            "that runs the release gate is not the interpreter that runs the code."
        ),
        fix=(
            "Pin the dev venv to 3.12 (a `.python-version` for uv/pyenv, or a documented "
            "`python3.12 -m venv backend/.venv` bootstrap step) and set "
            "`requires-python = \">=3.12,<3.13\"` in `backend/pyproject.toml:4` unless 3.14 support is "
            "intended and tested in CI."
        ),
        notes=(
            "Hygiene finding F18 (Python 3.14 bytecode leftovers in a 3.12 project) is covered here — the "
            "`__pycache__` directories should be deleted before packaging. Couples with OPS-18, whose "
            "bootstrap target is where the 3.12 venv should be created."
        ),
    ),
    dict(
        id="OPS-14",
        column="QA_TESTED",
        title="Two copies of @tanstack/query-core ship in the frontend bundle",
        sev="medium",
        area="ops",
        labels=["ops", "performance"],
        effort="S",
        evidence_log=[
            'QA 2026-09-24 (orchestrator, first-hand): unit 2299 passed + ruff clean; integration 130 passed (Postgres 16 disposable DB, alembic head); frontend tsc/eslint/vitest 593 green; e2e chromium 4 and Mobile Chrome 4 green against the real backend',
        ],
        problem=(
            "`frontend/package.json` pins `@tanstack/query-core` exactly while floating "
            "`@tanstack/react-query` on a caret range, so npm resolves a nested second copy of the query "
            "core. `package-lock.json` is what CI and the Docker build install from, so the skew ships."
        ),
        evidence=[
            "`frontend/package.json:33` — `\"@tanstack/query-core\": \"5.90.20\"` pinned exactly; `:34` — `\"@tanstack/react-query\": \"^5.90.21\"` floating.",
            "`frontend/package-lock.json:6304-6307` resolves root `@tanstack/query-core@5.90.20`; `:6360-6364` resolves a **nested** `node_modules/@tanstack/react-query/node_modules/@tanstack/query-core@5.101.0`.",
            "`frontend/Dockerfile:9` — `npm ci` installs from `package-lock.json`, so the split resolution is what actually ships.",
            "`TECH.md:23` — the stack already needs aggressive chunking.",
        ],
        impact=(
            "Two copies of the query core in one bundle means duplicated, version-skewed internals behind a "
            "single `QueryClient`: react-query 5.101's core helpers can behave differently from the "
            "5.90.20 that direct-import sites link against, and ~30-60 KB of dead JS ships."
        ),
        fix=(
            "Drop the exact pin (or align it to the resolved version) so npm hoists a single `query-core`, "
            "and add an assertion to CI that `npm ls @tanstack/query-core` prints one tree. Consider a "
            "general dedupe guard for the React/RA/TanStack trio."
        ),
        notes="Merge with DOC-12 — the second JS lockfile in the same tree is the other half of the frontend dependency-resolution problem.",
    ),
    dict(
        id="OPS-15",
        column="QA_TESTED",
        title="Dev-only mock servers and the env template ship into the production backend image",
        sev="medium",
        area="ops",
        labels=["ops", "security"],
        effort="S",
        evidence_log=[
            'QA 2026-09-24 (orchestrator, first-hand): unit 2299 passed + ruff clean; integration 130 passed (Postgres 16 disposable DB, alembic head); frontend tsc/eslint/vitest 593 green; e2e chromium 4 and Mobile Chrome 4 green against the real backend',
        ],
        problem=(
            "`backend/.dockerignore` excludes `.venv`, `tests`, `.env*`, `Dockerfile`, "
            "`docker-compose*.yml` and `Caddyfile`, but not `mock_servers/` or `.env.example`. The image "
            "then runs `COPY . .`, so the fake Zalo endpoint used by `make dev` and the env template ride "
            "into production."
        ),
        evidence=[
            "`backend/.dockerignore` — excludes `.venv`, `tests`, `.env*`, `Dockerfile`, `docker-compose*.yml`, `Caddyfile`; `mock_servers/` and `.env.example` are absent from the list.",
            "`backend/Dockerfile:18` — `pip install -e .`; `:21` — `COPY . .`, which carries `mock_servers/zalo_mock.py`, the fake Zalo inbound/outbound endpoint used by `make dev` (`backend/Makefile:82`).",
            "`docs/deployment-guide.md:56` — the smoke gate already stubs LLM and Zalo, so the mock is not needed inside the image.",
            "[INFERENCE] That the mock is *reachable* on the production compose network is inferred from `.dockerignore` plus `COPY . .`; it was not observed at runtime.",
        ],
        impact=(
            "A webhook-shaped mock server and the env template are importable inside the production "
            "compose network, widening the surface for an attacker who already has container access and "
            "muddying \"what is production code\"."
        ),
        fix=(
            "Add `mock_servers` and `.env.example` to `backend/.dockerignore`; if `smoke_turn` needs a "
            "stubbed channel, keep the stub inside `backend/scripts/` or `backend/tests/`."
        ),
        notes="Merge with OPS-11 — both are single-file trims of the backend image.",
    ),
    dict(
        id="OPS-16",
        column="QA_TESTED",
        title="Nine migrations have fake or absent downgrades and no check exercises alembic downgrade",
        sev="medium",
        area="ops",
        labels=["ops", "tech-debt"],
        effort="M",
        evidence_log=[
            'QA 2026-09-24 (orchestrator, first-hand): unit 2299 passed + ruff clean; integration 130 passed (Postgres 16 disposable DB, alembic head); frontend tsc/eslint/vitest 593 green; e2e chromium 4 and Mobile Chrome 4 green against the real backend',
        ],
        problem=(
            "Of 55 revisions plus one merge node, nine have `pass`, a `RuntimeError` or nothing in "
            "`downgrade()`. `release-check` asserts only that there is one head, no target, test or CI "
            "job runs `alembic downgrade`, and `make restore` stamps a historical dump as head with "
            "`|| true`, which hides drift."
        ),
        evidence=[
            "Fake or absent downgrades: `backend/alembic/versions/0001_baseline.py:622-626` (`raise RuntimeError`), `0007_conversation_semi_auto.py:22-25`, `0008_drop_bus_timetable_fn.py:26-30`, `0010_drop_dead_schema_objects.py:43-46`, `0018_backfill_conversation_leads.py:42-44`, `0024_delivery_read_states.py:28-31`, `0029_delivery_status_sending.py:30-33`, `0030_delivery_status_send_unknown.py:33-36` (all `pass`), and the merge node `091e7edc9f76_merge_0013_password_reset_otps_0013_.py:22-23`.",
            "`Makefile:19` — `release-check` asserts exactly one alembic head and nothing more; no target, test or CI job runs `alembic downgrade`.",
            "`Makefile:119-120` — `make restore` runs `alembic stamp head 2>/dev/null || true`, so a restored DB can claim a revision whose DDL it does not have and nothing will ever notice.",
            "`backend/alembic/env.py:6-7,26` — the ORM does not generate migrations and `target_metadata` is wired only for future autogenerate, so nothing mechanically checks `backend/app/models/` against the migrations.",
            "Well-behaved references to hold the line with: `0014_retrieval_scaling_indexes.py:57-87`, `0016_query_perf_indexes.py:54-162` and `0013_proactive_followup.py:44-49`.",
        ],
        impact=(
            "`alembic downgrade` is effectively non-functional for the 0001-0018 range and for four enum "
            "additions, so a future engineer discovering a bad deploy has to reconstruct DDL from git. "
            "Stamping a restored dump as head means the local DB can claim a revision whose DDL it does "
            "not match, invisibly."
        ),
        fix=(
            "For each `pass`, record the intent in a module-level comment plus a greppable marker — "
            "`# downgrade: INTENTIONAL_NOOP — <reason>` for 0007/0018/0024/0029/0030 and "
            "`# downgrade: FORWARD_ONLY — recover DDL from <path>` for 0008/0010. Add a CI step running "
            "`alembic upgrade head && alembic downgrade -1 && alembic upgrade head` on a throwaway "
            "Postgres, skipping the forward-only revisions via an explicit allow-list. Replace "
            "`alembic stamp head` in `Makefile:119-120` with a real `upgrade head`, or at minimum assert "
            "the stamped revision equals the dump's `alembic_version` row."
        ),
        notes="Merge with OPS-20 — the `stamp head` line is one of the five low findings, and the revision-naming drift makes filename-to-revision correlation unreliable.",
    ),
    dict(
        id="OPS-17",
        column="QA_TESTED",
        title="Later migrations create indexes non-concurrently against live tables",
        sev="medium",
        area="ops",
        labels=["ops", "performance"],
        effort="S",
        evidence_log=[
            'QA 2026-09-24 (orchestrator, first-hand): unit 2299 passed + ruff clean; integration 130 passed (Postgres 16 disposable DB, alembic head); frontend tsc/eslint/vitest 593 green; e2e chromium 4 and Mobile Chrome 4 green against the real backend',
        ],
        problem=(
            "Five migrations after the baseline issue plain `CREATE INDEX`/`CREATE UNIQUE INDEX` on "
            "existing tables, unlike `0014` and `0016`, which correctly use `CREATE INDEX CONCURRENTLY` "
            "inside `op.get_context().autocommit_block()`. `bg_deploy.sh` runs migrations while the old "
            "colour keeps serving, so a slow lock turns into queued candidate writes."
        ),
        evidence=[
            "`backend/alembic/versions/0039_multi_vertical_ingestion_templates.py:152` (`CREATE UNIQUE INDEX uq_active_kb_version_per_project ON kb_versions`), `0031_conversation_seq_and_trace_id.py:52` (`ix_bot_runs_trace_id`), `0036_outbound_outbox.py:110` (`ix_outbound_outbox_pending_created`), `0009_feature_catalog_active.py:46`, `0017_replace_lead_stage_flow.py:43,75` (recreating `leads_stage_idx` right after an `ALTER TYPE`).",
            "`backend/alembic/versions/0014_retrieval_scaling_indexes.py:57-79` and `0016_query_perf_indexes.py:54-135` — the correct pattern (`CONCURRENTLY` inside `autocommit_block()`).",
            "`backend/alembic/env.py:46-49` and `backend/alembic.ini` — no `lock_timeout`, so nothing bounds the wait (see OPS-07).",
            "[INFERENCE] Table sizes in production are unknown (no DB access), so the lock impact is characterised as pattern risk rather than an active incident; no rewrite byte-size was measured.",
        ],
        impact=(
            "`CREATE INDEX` takes a write-blocking lock on its table, and `backend/scripts/bg_deploy.sh` "
            "runs migrations while the old colour serves, so a slow lock queues candidate writes. Today's "
            "tables (`kb_versions`, `bot_runs`) are not the hot path, but with no `lock_timeout` the next "
            "migration on `messages`/`leads`/`conversations` will stall the deploy silently."
        ),
        fix=(
            "Require `CONCURRENTLY` + `autocommit_block()` for all index DDL on existing tables, state it "
            "in `docs/code-standards.md`, and set `lock_timeout` on the migration connection (OPS-07). "
            "Because `CONCURRENTLY` leaves an INVALID index on failure, add a post-deploy check that no "
            "index has `indisvalid = false`."
        ),
        notes="Merge with OPS-07 — the lock timeout belongs to the same migration path.",
    ),
    dict(
        id="OPS-18",
        column="QA_TESTED",
        title="make dev cannot work from a clean clone and no document says how to bootstrap",
        sev="medium",
        area="ops",
        labels=["ops", "documentation"],
        effort="S",
        evidence_log=[
            '29446018 — idempotent `make bootstrap` (env, venv on 3.12, npm ci) and `dev` depends on it',
            'c37ef6a5 — root README.md with the one-command path; qa-runbook seed path fixed',
            'verified: make -n bootstrap / make -n dev produce the expected guarded commands',
            'QA 2026-09-24 (orchestrator, first-hand): unit 2299 passed + ruff clean; integration 130 passed (Postgres 16 disposable DB, alembic head); frontend tsc/eslint/vitest 593 green; e2e chromium 4 and Mobile Chrome 4 green against the real backend',
        ],
        problem=(
            "There is no root `README.md`, and no document contains a `python -m venv` or `npm ci` step. "
            "`make dev` prints \"Starting VFIC dev environment\" and then dies twice — once because "
            "`backend/.venv/bin/python` does not exist, and once because `frontend/node_modules` is "
            "missing."
        ),
        evidence=[
            "No root `README.md` exists; grepping `docs/`, `TECH.md` and `AGENTS.md` for `python -m venv|pip install -e|npm ci|npm install` returns only architecture prose and `make dev` usage.",
            "`backend/Makefile:12` — `PY := ./.venv/bin/python`; the `dev` recipe hard-fails at `$(PY) -m uvicorn` (`:82`) and spawns `(cd ../frontend && exec npm run dev …)` (`:85`), which fails without `frontend/node_modules`.",
            "`backend/Makefile:33-34` — the `db` target degrades silently via `|| echo`, so the missing venv is hidden there and only surfaces later.",
            "`docs/qa-runbook.md:31-32` claims `make dev` seeds the DB, and `docs/troubleshooting/README.md:67` tells users to change `PORT` — neither is true (see OPS-12, OPS-19).",
        ],
        impact=(
            "A new engineer cannot get a working stack in one command, and the failure messages "
            "(`/bin/sh: ./.venv/bin/python: No such file`) point at the Makefile rather than at the "
            "missing bootstrap."
        ),
        fix=(
            "Add a `bootstrap` (or `setup`) target — `python3.12 -m venv backend/.venv && "
            "backend/.venv/bin/pip install -e 'backend/.[dev]'` plus `npm ci --prefix frontend` — make "
            "`dev` depend on it guarded by `test -d`, and write a short root `README.md` whose first "
            "heading is the one-command path. Also fix `docs/qa-runbook.md:31-32` (seeding) and "
            "`docs/troubleshooting/README.md:67`."
        ),
        notes="Merge with OPS-13 (the bootstrap target is where the 3.12 venv gets pinned), OPS-19 (the port override) and DOC-10 (missing root README).",
    ),
    dict(
        id="OPS-19",
        column="QA_TESTED",
        title="Dead PORT plumbing between the root and backend Makefiles",
        sev="medium",
        area="ops",
        labels=["ops", "documentation"],
        effort="S",
        evidence_log=[
            '29446018 — root PORT deleted as dead plumbing; dev forwards FRONTEND_PORT (the variable backend reads)',
            'verified: make -n dev shows FRONTEND_PORT=$(PORT); backend/Makefile never references PORT',
            'QA 2026-09-24 (orchestrator, first-hand): unit 2299 passed + ruff clean; integration 130 passed (Postgres 16 disposable DB, alembic head); frontend tsc/eslint/vitest 593 green; e2e chromium 4 and Mobile Chrome 4 green against the real backend',
        ],
        problem=(
            "The root Makefile documents `make dev PORT=9000` and forwards `PORT` to `backend/Makefile`, "
            "which never references it — it defines `BACKEND_PORT`, `FRONTEND_PORT` and `ZALO_MOCK_PORT` "
            "instead. The troubleshooting doc repeats the same dead override."
        ),
        evidence=[
            "`Makefile:3-13` — documents \"Port shared by backend (uvicorn) and frontend (Vite) … `make dev PORT=9000`\" and invokes `$(MAKE) -C backend dev PORT=$(PORT)`.",
            "`backend/Makefile:3-5` — defines `BACKEND_PORT ?= 8000`, `FRONTEND_PORT ?= 5173`, `ZALO_MOCK_PORT ?= 8788` and never references `PORT`; its own comment at `:63` tells users to `make dev BACKEND_PORT=8001`.",
            "`docs/troubleshooting/README.md:67` — \"Port 5173 (or custom `PORT`) in use?\" — an override that does nothing.",
        ],
        impact=(
            "The documented override silently does not apply: a user with port 5173 busy gets the same "
            "failure they were trying to fix, and no diagnostic."
        ),
        fix=(
            "Delete `PORT` from `Makefile:3-13` and forward the three real variables (`BACKEND_PORT`, "
            "`FRONTEND_PORT`, `ZALO_MOCK_PORT`), or make `backend/Makefile:3-5` honour `PORT` as a "
            "fallback for `FRONTEND_PORT`; fix `docs/troubleshooting/README.md:67` to match."
        ),
        notes="Merge with OPS-18 — the same first-run path.",
    ),
    # --------------------------------------------------------------------- LOW
    dict(
        id="OPS-20",
        column="QA_TESTED",
        title="Low-severity restore, backup, dev-exposure, release-gate and migration-naming hygiene",
        sev="low",
        area="ops",
        labels=["ops", "security"],
        effort="S",
        evidence_log=[
            'Landed: ON_ERROR_STOP restore, password-reset prompt (FORCE=1), mktemp+trap, -Fc -Z6 + pg_restore, compose-resolved containers, retention of 10, loopback dev ports, uv lock --check, npm ci',
            'REMAINING: the filename==revision check (+ the two drifted revisions) — alembic/versions is approval-gated; renaming IDs would break deployed alembic_version rows',
            'Decision: no dev Redis password — loopback binding is the control (e2e harness pins a passwordless URL); documented in docker-compose.dev.yml',
            'QA 2026-09-24 (orchestrator, first-hand): unit 2299 passed + ruff clean; integration 130 passed (Postgres 16 disposable DB, alembic head); frontend tsc/eslint/vitest 593 green; e2e chromium 4 and Mobile Chrome 4 green against the real backend',
        ],
        problem=(
            "Five low-severity defects share one theme: the local tooling hides its own failures. "
            "`make restore` mutates a restored DB and resets every password, `make backup` leaves "
            "droppings, the dev compose file exposes Postgres and Adminer on all interfaces, "
            "`release-check` cannot detect the lockfile-drift class, and migration filenames no longer "
            "match their revision IDs."
        ),
        evidence=[
            "`Makefile:113-125` — `make restore` drops and recreates `vfic`, loads the dump with `ON_ERROR_STOP` left at psql's default (unlike `scripts/restore-droplet.sh:113`, which sets `-v ON_ERROR_STOP=0` explicitly), runs `alembic stamp head 2>/dev/null || true`, then `scripts.reset_passwords --password admin123` for **all** users.",
            "`Makefile:83-95` — the dump is written to `/tmp/` and removed only on the success path, historical `vfic_pg_backup_*.sql.gz` are never pruned, plain-SQL format (no `-Fc`) prevents parallel or selective restore, and `docker exec vfic-postgres-1` (`:85`) is hardcoded to the `/opt/vfic` compose project name.",
            "`backend/docker-compose.dev.yml:10` (`ports: [\"5432:5432\"]`) and `:34` (`8082:8080`) bind `0.0.0.0` with credentials `vfic/vfic` (`:8-9`) and a passwordless Redis on `6382` (`:13-16`), while `backend/docker-compose.yml:226` correctly binds Adminer to `127.0.0.1:8081`.",
            "`Makefile:16-19` — `release-check` checks a clean worktree, `git diff --check` and exactly one alembic head, but never lockfile consistency (`uv lock --check`, `npm ci` vs `npm install`); `frontend/Makefile:9-10`'s `install` uses `npm install` while `frontend/Dockerfile:9` and `.github/workflows/quality-gates.yml` use `npm ci`.",
            "`backend/alembic/versions/0030_delivery_status_send_unknown.py:22` declares `revision = \"0030_send_unknown\"`, `0031_conversation_seq_and_trace_id.py:28` declares `\"0031_conversation_seq_trace\"`, two files share the `0013_` prefix (`0013_password_reset_otps.py`, `0013_proactive_followup.py`, joined by `091e7edc9f76_merge_0013_password_reset_otps_0013_.py:12-13`), and `docs/deployment-guide.md:296-300` asks for ≤32-char revision IDs while `0053_single_page_external_source_sync_state` is 41.",
        ],
        impact=(
            "A partially failed local restore is reported as success, and a well-known password "
            "(`admin123`) is sprayed across every account if the restore is ever pointed at a shared "
            "environment; failed backup downloads accumulate on the droplet; anyone on an untrusted LAN "
            "can read the dev database, which is typically a copy of production data; the one gate that "
            "runs before a push cannot see the dependency-drift class; and "
            "`grep revision = \"0031_conversation_seq_and_trace_id\"` finds nothing, so "
            "filename-to-`alembic_version` correlation is unreliable."
        ),
        fix=(
            "Warn before the password reset in `Makefile:113-125` and fail the target when psql reports an "
            "error; use `mktemp` plus a trap, `pg_dump -Fc -Z6`, retention of the last N dumps, and "
            "`docker compose ps -q postgres` instead of the literal container name; bind the dev ports to "
            "`127.0.0.1:` and set a dev `REDIS_PASSWORD`; add `uv lock --check` to `release-check` and "
            "switch `frontend/Makefile:9-10` to `npm ci`; and enforce filename == revision ID with a "
            "check, renaming the two drifted revisions."
        ),
        notes="Merge with OPS-05 (lockfile policy), OPS-16 (`stamp head`) and OPS-03 (restore correctness) when touching the same targets.",
    ),
    # ------------------------------------------------------------ DOCS / REPO
    dict(
        id="DOC-01",
        column="QA_TESTED",
        title="openwiki/INSTRUCTIONS.md documents a different product and steers the wiki agents are told to consult",
        sev="critical",
        area="docs",
        labels=["documentation", "tech-debt"],
        effort="S",
        evidence_log=[
            'QA 2026-09-24 (orchestrator, first-hand): unit 2299 passed + ruff clean; integration 130 passed (Postgres 16 disposable DB, alembic head); frontend tsc/eslint/vitest 593 green; e2e chromium 4 and Mobile Chrome 4 green against the real backend',
        ],
        problem=(
            "`openwiki/INSTRUCTIONS.md` describes TingTing as a Vietnamese trucking-logistics platform "
            "built as a TypeScript monorepo with Express v5, Drizzle ORM, Casbin RBAC and a `shared/` "
            "package — none of which exist here. `AGENTS.md` tells agents to treat the generated "
            "`openwiki/` index as an evidence source, and a tracked CI workflow regenerates it weekly "
            "from that brief, so the wiki is generated against a fictional architecture."
        ),
        evidence=[
            "`openwiki/INSTRUCTIONS.md:11-13` — \"TingTing … is a Vietnamese **trucking logistics platform** for managing trips, drivers, customers, fleet vehicles, and financials\"; `:14-24` claims \"a TypeScript monorepo with three packages\", \"`backend/` — Express v5 + TypeScript API on port 3090; **Drizzle ORM**… **Casbin RBAC**\", \"`frontend/` — React **18**\" and \"`shared/`\".",
            "`backend/pyproject.toml:2` is FastAPI, and `.git/index` shows `backend/app/**` is Python with no `shared/` directory anywhere.",
            "`openwiki/INSTRUCTIONS.md:26-32` invents roles (`ACCOUNTANT`, `DRIVER`), a trip lifecycle (`PENDING → IN_PROGRESS → COMPLETED → SETTLED`) and VND money math; `:39-46` points at `docs/flows/DELIVERY_TRIP_LIFECYCLE.md`, `docs/company-files/`, `TASKS.md` and `shared/src/calculations/` — none of which exist in this repo.",
            "`AGENTS.md:88-92` — \"This repository has a generated `openwiki/` evidence index… Treat source code and tests as authoritative\"; `.github/workflows/openwiki-update.yml` is tracked, so CI regenerates the wiki weekly from the wrong brief.",
            "Staleness compounds it: `openwiki/.last-update.json` records `updatedAt 2026-09-21T12:39:13Z` with `status: \"interrupted\"`, while `openwiki/.page-manifest.json:1-33` stamps every page with a different `gitHead` (`10de99a…`) than either the run file or current HEAD `923b1d3`.",
        ],
        impact=(
            "The AI evidence index is generated against a fictional architecture, so any agent that "
            "follows `AGENTS.md` into `openwiki/` gets confidently wrong guidance about stack, layering "
            "and domain — and the weekly CI job keeps regenerating it, so the wrongness is self-renewing. "
            "It also explains why the pages are low-value."
        ),
        fix=(
            "Rewrite `openwiki/INSTRUCTIONS.md` from `TECH.md` plus `docs/system-architecture.md`, or "
            "delete `openwiki/` entirely and remove `.github/workflows/openwiki-update.yml` and the "
            "`AGENTS.md:88-92` OpenWiki block. Do not hand-edit page files. Also remove the "
            "`.claude/skills/**` and `.claude/hooks/**` re-includes from `.openwikiignore:20-25` so "
            "generation is driven by product source rather than 1,801 vendor skill files."
        ),
        notes="Hygiene finding F11 (openwiki staleness) is covered here. If the brief is not fixed first, deleting `openwiki/` is the cheaper option.",
    ),
    dict(
        id="DOC-02",
        column="QA_TESTED",
        title="AGENTS.md routes to three skill paths that no longer exist and mis-paths the smoke script",
        sev="high",
        area="docs",
        labels=["documentation"],
        effort="S",
        evidence_log=[
            'AGENTS.md task routing now points at skill paths that exist (ak-cook/ak-debug) and backend/scripts/smoke_turn.py',
            'verified: every routed path exists on disk',
            'QA 2026-09-24 (orchestrator, first-hand): unit 2299 passed + ruff clean; integration 130 passed (Postgres 16 disposable DB, alembic head); frontend tsc/eslint/vitest 593 green; e2e chromium 4 and Mobile Chrome 4 green against the real backend',
        ],
        problem=(
            "The always-loaded constitution points at three `.claude/skills/*` paths that have been "
            "deleted, at a `.omc/skills/` directory that contains no skills, and at "
            "`scripts/smoke_turn.py` when the file lives at `backend/scripts/smoke_turn.py`. The same "
            "broken-hook claim appears in `docs/agent-development-kit.md`."
        ),
        evidence=[
            "`AGENTS.md:71` → `.claude/skills/implement-change/SKILL.md`, `:72` → `.claude/skills/verify-change/SKILL.md`, `:73` → `.claude/skills/qa-dev-environment/SKILL.md` — all three missing from the tree.",
            "`AGENTS.md:75` — \"relevant `.omc/skills/` expertise\"; `.omc/` contains only `project-memory.json`, `state/` and `sessions/`, with no `skills/` at all.",
            "`AGENTS.md:78` — \"passes `scripts/smoke_turn.py`\"; the actual path is `backend/scripts/smoke_turn.py`.",
            "`docs/agent-development-kit.md:16-17` names `.claude/hooks/project-guard.py`, which does not exist, while `.claude/settings.json` registers `descriptive-name.cjs`/`privacy-block.cjs`/`scout-block.cjs`; the doc's verification command at `:38` (`scripts/agent/test-project-guard.py`, which *is* tracked) therefore tests an unwired guard.",
            "The three repo skills survive only inside the stale `repomix-output.xml`; the live `skills/` tree is 106 vendor `ak-*` directories, so the discovery path works and the targets are simply gone.",
        ],
        impact=(
            "Implementation, verification and QA routing — the three primary workflows — dead-ends on the "
            "first tool call, so agents improvise instead of following repo procedure."
        ),
        fix=(
            "Repoint `AGENTS.md:71-75` at real targets (`.claude/skills/ak-cook/`, an `ak-debug` or "
            "verification equivalent, `standards/agent-completion-checklist.md`) or restore the three "
            "repo skills; fix the `backend/scripts/smoke_turn.py` path at `AGENTS.md:78` and the two "
            "claims in `docs/agent-development-kit.md:16,38`."
        ),
        notes="Merge with DOC-05 — the same missing `project-guard.py` and the same `.claude` tree.",
    ),
    dict(
        id="DOC-03",
        column="QA_TESTED",
        title="Documentation drift cluster — every checked claim in TECH.md and codebase-summary.md except one is wrong",
        sev="high",
        area="docs",
        labels=["documentation"],
        effort="M",
        evidence_log=[
            'QA 2026-09-24 (orchestrator, first-hand): unit 2299 passed + ruff clean; integration 130 passed (Postgres 16 disposable DB, alembic head); frontend tsc/eslint/vitest 593 green; e2e chromium 4 and Mobile Chrome 4 green against the real backend',
        ],
        problem=(
            "Seventeen facts in the two documents that `AGENTS.md`/`TECH.md` designate as sources of truth "
            "are contradicted by the code — the auth library, the migration head, the entity count, the "
            "queue set, the service topology and ten line numbers among them. The auth row is actively "
            "dangerous: it describes a CVE-bearing library this repo deliberately removed."
        ),
        evidence=[
            "**Auth library.** `TECH.md:29` says \"**python-jose** JWT\" and `docs/codebase-summary.md:160` says \"python-jose HS256 JWT\"; `backend/app/core/security.py:23` is `import jwt` (PyJWT), `:10-15` documents the migration (\"PyJWT replaced python-jose… python-jose 3.5.0 still pulls `ecdsa` (CVE-2024-23342)\"), and `backend/pyproject.toml` declares `pyjwt[crypto]>=2.9.0` with no jose.",
            "**Migration head.** `TECH.md:21` says \"0001–0053, current head `0053_single_page_external_source_sync_state`\" and `docs/codebase-summary.md:40` says \"migrations through 0050\"; `backend/alembic/versions/0054_channel_account_projects.py` is tracked and is the single head — 4 versions behind the code, 2 behind its own sibling doc.",
            "**Counts and topology.** `TECH.md:79` says \"21 entities\" against 65 `__tablename__` classes across `backend/app/models/*.py` (3.1× understated); `TECH.md:24` says \"**4 queues**\" and `TECH.md:143` names a `chat` queue, while `backend/docker-compose.yml:84,116,139,175` consumes five queues (`webhook_high`, `recovery`, `persistence_low`, `ingest`, `followup`) and no `chat` queue exists; `docs/codebase-summary.md:187` says \"**10-service** prod stack (… worker-chatbot **×6** …)\" while compose defines 13 services with `web-blue` **and** `web-green` and `worker-chatbot: replicas: 3` (`backend/docker-compose.yml:87`).",
            "**Ten stale line numbers** in `docs/codebase-summary.md:163-173`: `BotRunState`/`GraphDeps` cited at `:163` are at `backend/app/graph/types.py:37`/`:118`; `build_deps` at `:164` is at `backend/app/graph/factories.py:760`; `GeminiEmbedder` at `:165` is at `backend/app/graph/clients.py:531`; the Zalo senders at `:170-172` are at `backend/app/services/zalo_sender.py:22`, `zalo_bot_service.py:347`, `zalo_oa_service.py:64` (endpoint at `:289/:360/:367/:415`); retrieval \"(line 160)\" at `:173` is `backend/app/services/retrieval/repository.py:34`/`:222`.",
            "**Library, README, remote and paths.** `TECH.md:41` says virtualization is \"**react-virtuoso** `^4.18` — all long lists\" while `frontend/src/components/atomic-crm/conversations/presentation/ChatThread.tsx:14` is `import { VList } from \"virtua\"` (virtuoso survives only in `dashboard/RecruitingCommandCenter.tsx:5`); `docs/codebase-summary.md:85` claims a root `README.md` that does not exist; `:3` names remote `git@github.com:4rankng/ChatBotN8N.git` against `.git/config`'s `vfic-chatbot.git`; `:208`/`:75` give the wrong `inbox.css` path and 10 vs 19 CSS files. `docs/codebase-summary.md:100-101`'s LOC table is **[UNVERIFIED]** — no `cloc` was available, and measured file-size anchors suggest the per-area figures are low.",
        ],
        impact=(
            "~17 wrong facts mislead capacity reasoning on the 2 vCPU box (entity, queue and service "
            "counts), send readers to unrelated code (ten line-number claims), and one row describes "
            "`python-jose` — the library this repo deliberately migrated away from because of "
            "CVE-2024-23342."
        ),
        fix=(
            "Treat `docs/codebase-summary.md` as a generated artifact: regenerate it from the tree (or "
            "delete it and keep only `TECH.md` plus `docs/system-architecture.md`); make the key-files "
            "table symbol-based (\"`BotRunState` in `app/graph/types.py`\") rather than line-based; run one "
            "`cloc` pass and replace the LOC table; and add the two fastest-drifting facts (migration "
            "head, entity count) to a CI check."
        ),
        notes="Merge with OPS-12 (operator-critical knobs, same drift class) and DOC-11 (staleness); the missing root `README.md` row is also DOC-10.",
    ),
    dict(
        id="DOC-04",
        column="QA_TESTED",
        title="plans/ is gitignored while AGENTS.md and the completion checklist mandate writing reports there",
        sev="high",
        area="docs",
        labels=["documentation", "ops"],
        effort="M",
        evidence_log=[
            'plans/reports/ is no longer gitignored: root rules plans/* + !plans/reports/ + !plans/qa-*/ (a nested .gitignore cannot re-include)',
            'verified against the vendored gitignore-spec engine: reports are ignored=false, per-plan dirs ignored=true',
            'QA 2026-09-24 (orchestrator, first-hand): unit 2299 passed + ruff clean; integration 130 passed (Postgres 16 disposable DB, alembic head); frontend tsc/eslint/vitest 593 green; e2e chromium 4 and Mobile Chrome 4 green against the real backend',
        ],
        problem=(
            "`.gitignore` ignores `plans/`, yet `AGENTS.md` and "
            "`standards/agent-completion-checklist.md` instruct agents to copy completion records into "
            "`plans/reports/`. Eleven legacy reports remain tracked while six newer ones are untracked "
            "and will never be committed, and tracked docs link to ~10 plan directories that no longer "
            "exist."
        ),
        evidence=[
            "`.gitignore:8` ignores `plans/`; `.git/index` still contains 11 tracked `plans/reports/*.md` (the `260723-*` set plus `260724-1720`), while the working tree holds 17 reports — `260913-2335`, `260921-1055`, `260921-2153`, `research-260921-1953`, `260922-2141` and `260924-1416` are untracked.",
            "`AGENTS.md:61` — \"Copy `standards/agent-completion-checklist.md` to `plans/reports/<YYMMDD-HHmm>-<slug>-completion.md`\"; the same instruction appears at `standards/agent-completion-checklist.md:4`, and QA records are mandated at `docs/qa-runbook.md:430,511`.",
            "Dangling references include `docs/chatbot-latency-improvement-plan.md:24,102,330` (`plans/20260710-chatbot-performance/`), `:332` (`plans/2026-07-12-performance-endpoint-latency/`), `docs/design-tokens-warm-paper.md:223` (`plans/260710-1322-frontend-ui-ux-redesign/`), `docs/decisions/0010-provider-returned-agent-reasoning.md:44` and `docs/journals/260712-performance-endpoint-alembic-double-head.md:10`.",
            "All six surviving plan directories are already-shipped work, proven by the commit log in `.git/logs/HEAD`: `runner-lane-pipeline`→`40ee8f5`, `conversation-state-split`→`1ddfa99`, `knowledge-projection-seam`→`93e654e`, `settings-provider-panel`→`6d2655c`, `llm-income-typed-seam`→`83f4f23`, `custom-context-window`→`a5c4e21`.",
        ],
        impact=(
            "The mandated completion and QA evidence trail is invisible to git — no reviewable artifacts, "
            "no blame, no history for the last six reports — while 11 stale reports stay tracked and "
            "referenced docs point at deleted directories, so \"check `plans/` for overlap\" "
            "(`AGENTS.md:54`) yields either nothing or the wrong thing."
        ),
        fix=(
            "Decide the policy and encode it: either track `plans/` (remove `plans/` from `.gitignore:8`, "
            "`git add plans/`) or keep it local and repoint the convention at a tracked path such as "
            "`docs/reports/<YYMMDD-HHmm>-<slug>.md`. Then delete the six shipped plan directories — the "
            "work is in git history — and fix the ~10 dangling references; `git rm --cached -r "
            "plans/reports` if going the local route."
        ),
        notes="Merge with DOC-11 and DOC-10 — `docs/journals/` is currently the only populated durable-record path because `plans/` is ignored and `lessons/` is empty.",
    ),
    dict(
        id="DOC-05",
        column="QA_TESTED",
        title="Three parallel agent-config systems, 1,858 tracked .claude files, and a hook that runs twice per prompt",
        sev="high",
        area="docs",
        labels=["documentation", "tech-debt"],
        effort="M",
        evidence_log=[
            '.claude/hooks/hooks.json deleted (its scripts were a strict subset of .claude/settings.json)',
            'settings.json UserPromptSubmit deduped 2 entries/6 invocations → 1/4, so hooks stop firing twice per prompt',
            'verified: json.load parses; all 14 registered hook scripts exist on disk; no loader reads the deleted manifest',
            'QA 2026-09-24 (orchestrator, first-hand): unit 2299 passed + ruff clean; integration 130 passed (Postgres 16 disposable DB, alembic head); frontend tsc/eslint/vitest 593 green; e2e chromium 4 and Mobile Chrome 4 green against the real backend',
        ],
        problem=(
            "`.claude/`, `.agentkit/` and `.omc/` are three competing sources of agent configuration with "
            "conflicting ignore rules; 1,858 `.claude` files are tracked while the subdirectories the "
            "team actually runs are not. `.claude/settings.json` and `.claude/hooks/hooks.json` register "
            "the same 13 hooks, and in both files the `UserPromptSubmit` block is duplicated."
        ),
        evidence=[
            "`.gitignore:44` ignores `/.claude/*` with only `/settings.json`, `/hooks/**` and `/skills/**` re-included (`:45-49`), so `.claude/agents/` (16 files), `.claude/rules/` (8), `.claude/output-styles/` (6), `.claude/ak-engineer-statusline.cjs` and `.claude/hooks/.logs/` sit on disk but are untracked.",
            "Tracked counts from the index `TREE` cache: `.claude` = 1,858 entries / 2 subtrees, `.claude/skills` = 1,801 entries / 106 subtrees, `.claude/hooks` = 56 entries / 3 subtrees.",
            "`.agentkit/` holds `ownership.json` (479.3 KB) and `script-audit.json` (218.0 KB); its `config.yaml` header says it is \"meant to be committed\" and `.agentkit/.gitignore` does `*` + `!config.yaml`, but root `.gitignore:9` wins — conflicting sources of truth for one directory. `.omc/` exists in 9 copies (`.gitignore:53`) and `AGENTS.md:75` still points at \"`.omc/skills/`\", which does not exist.",
            "`.claude/settings.json` and `.claude/hooks/hooks.json` register the same 13 hooks (one via `${CLAUDE_PROJECT_DIR}`, one via `${CLAUDE_PLUGIN_ROOT}`), and **both** duplicate the `UserPromptSubmit` block — two entries with `\"matcher\": \"*\"` each invoking `secret-output-guardrail.cjs`, with `simplify-gate.cjs` in both — so those hooks execute twice per prompt.",
            "`docs/agent-development-kit.md:16-17` points at `.claude/hooks/project-guard.py`, which does not exist.",
        ],
        impact=(
            "A fresh clone gets 1,858 vendor files but not the agents, rules and styles the team actually "
            "runs, and gets hook registrations whose duplicate `UserPromptSubmit` entries double prompt "
            "latency and token spend. Nobody can tell which tree is authoritative."
        ),
        fix=(
            "Pick one policy and encode it in `.gitignore`: either keep the vendor kit out of the product "
            "repo (ignore `.claude/skills/` and `.claude/hooks/`, commit only `settings.json` plus a "
            "pinned install script), or commit all three layers and drop the `/.claude/*` un-ignore maze. "
            "Either way, delete the duplicated `UserPromptSubmit` entry in `.claude/settings.json` and "
            "`.claude/hooks/hooks.json` (and `hooks.json` itself if `settings.json` is the live file), "
            "drop the `plans/`→`.omc` copies, and fix or delete `docs/agent-development-kit.md:16,38`."
        ),
        notes="Merge with DOC-02 (same missing `project-guard.py`) and DOC-12 (the two hook configs are also a duplication finding).",
    ),
    dict(
        id="DOC-06",
        column="QA_TESTED",
        title="repomix-output.xml is tracked at 4.8 MB although every ignore file classifies it as generated",
        sev="high",
        area="docs",
        labels=["documentation", "tech-debt"],
        effort="S",
        evidence_log=[
            'QA 2026-09-24 (orchestrator, first-hand): unit 2299 passed + ruff clean; integration 130 passed (Postgres 16 disposable DB, alembic head); frontend tsc/eslint/vitest 593 green; e2e chromium 4 and Mobile Chrome 4 green against the real backend',
        ],
        problem=(
            "A 4.8 MB stale text dump of the whole repository is tracked, while `.openwikiignore` lists it "
            "under generated artifacts and repomix's own header says it honours `.gitignore`. The dump "
            "predates the AgentKit install, so it mirrors a tree that no longer exists."
        ),
        evidence=[
            "`repomix-output.xml` is a literal entry in `.git/index`, between `plans/reports/260724-1720-smoke-lead-context-completion.md` and `scripts/agent/test-project-guard.py`, and is 4.8 MB at the repo root.",
            "`.gitignore` has no `repomix` rule, but `.openwikiignore:31-33` lists `.repomix*` and `repomix-output.xml` under \"Build output / caches / generated artifacts\".",
            "Staleness proof: the dump's `<directory_structure>` shows `.claude/` containing exactly `hooks/project-guard.py` and three skills, whereas the index shows 1,858 `.claude` files including 106 `ak-*` skills — and `project-guard.py` no longer exists.",
            "Residual leak check: the only credential-shaped hit is `repomix-output.xml:72529-72530` → `JWT_SECRET=change-me-please-32-chars-minimum-aaaa`, i.e. `.env.example` content; `backend/.env` is not in the dump.",
        ],
        impact=(
            "4.8 MB per clone for a stale mirror of the tree, plus a duplicate-context trap where an agent "
            "reads the old copy instead of the source, plus a standing risk that a future repomix run with "
            "a looser ignore config commits real env content."
        ),
        fix=(
            "Add `repomix-output.xml` and `.repomix*` to `.gitignore`, then `git rm --cached "
            "repomix-output.xml` and commit; keep future dumps outside the repo (`--output "
            "/tmp/repomix.xml`)."
        ),
        notes="Merge with DOC-07 — same class (generated or stray artifact tracked); the `.gitignore` rules belong in one commit.",
    ),
    dict(
        id="DOC-07",
        column="QA_TESTED",
        title="~21.2 MB of one-off marketing renders are tracked under assets/showoff",
        sev="high",
        area="docs",
        labels=["documentation", "tech-debt"],
        effort="S",
        evidence_log=[
            'QA 2026-09-24 (orchestrator, first-hand): unit 2299 passed + ruff clean; integration 130 passed (Postgres 16 disposable DB, alembic head); frontend tsc/eslint/vitest 593 green; e2e chromium 4 and Mobile Chrome 4 green against the real backend',
        ],
        problem=(
            "`assets/showoff/zalo-oa-architecture-flow/**` commits 18 PNGs at 0.87-1.9 MB each — every "
            "aspect-ratio × slide combination, uncompressed — for a one-time artifact with no runtime "
            "role. It is the single largest contributor to clone size."
        ),
        evidence=[
            "Six `horizontal-*.png` at 1.6-1.9 MB each (`images/horizontal-hero.png` 1.9 MB, `horizontal-recruiter-frontend.png` 1.8 MB, `horizontal-backend-brain.png` 1.8 MB, `horizontal-webhook-conduit.png` 1.7 MB, `horizontal-zalo-oa-bridge.png` 1.7 MB, `horizontal-e2e-flow.png` 1.6 MB) ≈ **10.25 MB**.",
            "Six `vertical-*.png` at 901 KB-1.0 MB ≈ **5.53 MB**; six `square-*.png` at 871-967 KB ≈ **5.28 MB**.",
            "Plus `index.html` 56.6 KB, `content.md` 10.1 KB and `capture.mjs` 3.1 KB → ≈ **21.2 MB** total, all tracked (`.git/index` `assets/showoff/…` = 21 entries / 1 subtree).",
            "[INFERENCE] The 55.1 MB pack is consistent with the current tree rather than a deleted giant blob, so this is live weight, not history.",
        ],
        impact=(
            "The largest single contributor to clone size and `.git` pack size, for an artifact no code "
            "reads; every aspect-ratio × slide combination is committed at 1-2 MB without compression."
        ),
        fix=(
            "Move the renders to object storage or a release artifact; if they must stay, keep only `.webp` "
            "at display resolution (~10× smaller) and `git rm --cached` the PNGs — `git rm -r --cached "
            "assets/showoff && printf 'assets/showoff/\\n' >> .gitignore` once the files are archived "
            "elsewhere."
        ),
        notes="Merge with DOC-06 — same `.gitignore` commit. Effort is M if the set is re-exported as webp.",
    ),
    dict(
        id="DOC-08",
        column="QA_TESTED",
        title="One-off probe and QA scripts are tracked in frontend/qa although the backend explicitly bans the practice",
        sev="medium",
        area="docs",
        labels=["documentation", "testing"],
        effort="S",
        evidence_log=[
            'QA 2026-09-24 (orchestrator, first-hand): unit 2299 passed + ruff clean; integration 130 passed (Postgres 16 disposable DB, alembic head); frontend tsc/eslint/vitest 593 green; e2e chromium 4 and Mobile Chrome 4 green against the real backend',
        ],
        problem=(
            "`frontend/qa/` tracks ten `probe-*.cjs`/`qa-*.cjs`/`ultraqa-sweep.cjs` leftovers plus "
            "`TEST_PLAN.md` and a generated `registry.json`, while `backend/.gitignore` states the "
            "opposite policy for the same artifact class in its own tree."
        ),
        evidence=[
            "Tracked in `frontend/qa/`: `probe-debug.cjs`, `probe-menu.cjs`, `probe-profile.cjs`, `probe-qc.cjs`, `probe-users.cjs`, `probe-users2.cjs`, `qa-audit.cjs`, `qa-audit2.cjs`, `qa-smoke.cjs`, `ultraqa-sweep.cjs`, `TEST_PLAN.md`.",
            "Also tracked and one-off or generated: `frontend/scripts/harness-monitor.mjs` (23.0 KB), `launch-harness.sh`, `clean-harness.sh`, `generate-registry.mjs`, `check-registry-paths.mjs` and `frontend/registry.json` (29.7 KB).",
            "`backend/.gitignore:24-27` — \"Local one-off debug / probe scripts (hardcoded dev paths; not rebuildable in the Docker image, so they must never ship)\" → `/probe_minimax_digest.py` and `/retry_lgdisplay.py` are ignored.",
        ],
        impact=(
            "Two contradictory policies for the same artifact class: the frontend copies are agent/QA "
            "leftovers, any hardcoded local path in them is a footgun for the next reader, and "
            "`registry.json` is shipped generated output."
        ),
        fix=(
            "Adopt the backend policy: `git rm --cached frontend/qa/probe-*.cjs frontend/qa/qa-audit*.cjs "
            "frontend/qa/ultraqa-sweep.cjs frontend/registry.json`, then add `frontend/qa/probe-*.cjs`, "
            "`frontend/qa/qa-audit*.cjs` and `frontend/registry.json` to `.gitignore`; keep `TEST_PLAN.md` "
            "and the two harness scripts if they are genuinely reusable."
        ),
        notes="Merge with DOC-10 — the same repo-hygiene pass over tracked stray artifacts.",
    ),
    dict(
        id="DOC-09",
        column="QA_TESTED",
        title="A 164.5 MB graph database is kept out of git only by a .gitignore inside its own untracked directory",
        sev="medium",
        area="docs",
        labels=["documentation", "tech-debt"],
        effort="S",
        evidence_log=[
            'QA 2026-09-24 (orchestrator, first-hand): unit 2299 passed + ruff clean; integration 130 passed (Postgres 16 disposable DB, alembic head); frontend tsc/eslint/vitest 593 green; e2e chromium 4 and Mobile Chrome 4 green against the real backend',
        ],
        problem=(
            "`.code-review-graph/graph.db` is 164.5 MB and correctly untracked, but the only rule keeping "
            "it out of git lives at `.code-review-graph/.gitignore` — inside the untracked directory "
            "itself. There is no root `.gitignore` rule, so a regenerated graph at a different path, or a "
            "tool that writes the DB before its `.gitignore`, would let `git add -A` pick up 164.5 MB."
        ),
        evidence=[
            "`.code-review-graph/graph.db` — 164.5 MB, absent from `.git/index`; ignored only by `.code-review-graph/.gitignore:1-3` (`*`, \"do not commit database files\").",
            "`.agentkit/ownership.json` 479.3 KB and `.agentkit/script-audit.json` 218.0 KB — untracked via root `.gitignore:9` plus `.agentkit/.gitignore`.",
            "Root `.omc/**` plus 8 nested copies (~40 files), `backend/vfic_backend.egg-info/`, `backend/.pytest_cache/`, `backend/.ruff_cache/` (incl. `0.15.22/`), `plans/.ruff_cache/`, `frontend/test-results/`, `frontend/.vitest-attachments/` (123.5 KB) and four `**/__screenshots__/` directories are all correctly untracked (root `.gitignore:66-68`, `backend/.gitignore`, `frontend/.gitignore:14,20`, `.gitignore:75`).",
            "Byte totals are measured from directory listings; the `.claude/**` working-tree size is **[EST]** (~11 MB, sampled from one module) and needs `du -sh .claude`.",
        ],
        impact=(
            "No clone cost today, but a real guardrail gap: the single most dangerous file in the working "
            "tree is protected by a rule that is itself untracked, so a path change or a write-ordering "
            "difference turns the next `git add -A` into a 164.5 MB commit. The MB-scale artifacts also "
            "cost local disk for no benefit."
        ),
        fix=(
            "Add `.code-review-graph/` to the root `.gitignore` and delete the MB-scale files when unused "
            "(`rm -rf .code-review-graph/graph.db .agentkit/ownership.json .agentkit/script-audit.json`), "
            "then add a periodic `git clean -ndX` review."
        ),
        notes="Merge with DOC-06/DOC-07 — all three are `.gitignore` hardening for artifacts the repo should never track.",
    ),
    dict(
        id="DOC-10",
        column="QA_TESTED",
        title="Repo-root sprawl — 22 top-level entries, 8 of them generated or stray",
        sev="medium",
        area="docs",
        labels=["documentation", "tech-debt"],
        effort="S",
        evidence_log=[
            'Landed: root README.md created with purpose/stack/bootstrap/commands/docs map',
            'REMAINING: the other sprawl dispositions (untracked artifacts committed earlier by the docs slice) are partly applied — verify each entry before closing',
            'QA 2026-09-24 (orchestrator, first-hand): unit 2299 passed + ruff clean; integration 130 passed (Postgres 16 disposable DB, alembic head); frontend tsc/eslint/vitest 593 green; e2e chromium 4 and Mobile Chrome 4 green against the real backend',
        ],
        problem=(
            "The repository root carries 22 top-level entries, eight of which are generated output, stray "
            "design or source files, or empty templates — `openwiki/`, `repomix-output.xml`, "
            "`assets/showoff/`, `pencil/`, `kb/`, `lessons/`, `design-qa.md` and the half-tracked "
            "`plans/`. A root `README.md` that `docs/codebase-summary.md` claims exists does not."
        ),
        evidence=[
            "Source and ops to keep: `backend/`, `frontend/`, `docs/` (77 entries / 5 subtrees), `standards/` (9 files), `scripts/`, `Makefile`, `.github/`, `AGENTS.md`, `CLAUDE.md`, `TECH.md`, `.gitignore`, `.openwikiignore`.",
            "Generated or stray: `openwiki/` (~45 files, generated and wrongly briefed — DOC-01), `repomix-output.xml` (4.8 MB — DOC-06), `assets/showoff/` (21 entries, ~21.2 MB — DOC-07), `pencil/` (2 `.pen` files, 77.3 + 89.1 KB), `kb/` (9 files incl. `RAW-Lich trinh xe bus.pdf` 284.1 KB and `RAW-AI.docx` 11.8 KB for the retired LG Display project), `lessons/` (`README.md` 3.6 KB, template-only, \"_No lessons recorded yet._\"), `design-qa.md` (10.5 KB, loose design-QA report) and `plans/`.",
            "`docs/codebase-summary.md:85` shows a root `└── README.md` that is absent from both the root listing and `.git/index`.",
            "`lessons/` duplicates the `docs/decisions/` + `docs/troubleshooting/` destinations that `docs/decisions/README.md:68` itself points to.",
        ],
        impact=(
            "Navigation and agent-context cost at the exact place every session starts, plus ~27 MB of "
            "stray tracked weight that has nothing to do with the product."
        ),
        fix=(
            "Keep the root to source + docs + ops: move `pencil/`→`design/`, `kb/`→`docs/kb-seed/` (or "
            "`backend/tests/fixtures/`), `assets/showoff/` out of the repo or under `docs/assets/` after "
            "webp conversion, `design-qa.md`→`docs/`, and either populate or delete `lessons/`. Add the "
            "missing root `README.md`."
        ),
        notes=(
            "Also folds two low findings that need no ticket of their own. **F14 stale remote refs** — "
            "`.git/packed-refs` has `refs/remotes/origin/main` packed at the old `08621c4` while the loose "
            "ref and local `main` are `923b1d3`, plus 15 stale Dependabot branches, two of them majors "
            "(`react-router-8.3.0`, `vitest-4.1.11`); fix with `git remote prune origin` after deciding "
            "the two majors, then `git gc --prune=now` if the pack does not shrink. **F17 unmanaged "
            "journals** — `docs/journals/` holds 38 files with no index and `AGENTS.md` never routes to "
            "it, while `docs/brainstorms/` (2) and `docs/research/` (1) are unindexed too; add "
            "`docs/journals/README.md` with a date/topic/commit table, or fold journals into "
            "`docs/decisions/` and delete `lessons/`."
        ),
    ),
    dict(
        id="DOC-11",
        column="QA_TESTED",
        title="Core docs are about two months stale relative to the code they describe",
        sev="medium",
        area="docs",
        labels=["documentation"],
        effort="M",
        evidence_log=[
            'QA 2026-09-24 (orchestrator, first-hand): unit 2299 passed + ruff clean; integration 130 passed (Postgres 16 disposable DB, alembic head); frontend tsc/eslint/vitest 593 green; e2e chromium 4 and Mobile Chrome 4 green against the real backend',
        ],
        problem=(
            "Five of the six core documents carry July timestamps while roughly 60 commits have landed "
            "since mid-September, including the TypeSafe Jev router replacement, gender inference, the "
            "context-window resolver and the Facebook Page work. `AGENTS.md` requires doc updates for "
            "exactly these change classes, so the drift is a process failure rather than a doc exemption."
        ),
        evidence=[
            "`docs/code-standards.md:3` \"Last updated: 2026-07-22\", `docs/codebase-summary.md:4` 2026-07-23, `docs/system-architecture.md:3` 2026-07-23, `docs/project-overview-pdr.md:4` 2026-07-24, `docs/deployment-guide.md:3` 2026-07-26; only `docs/project-roadmap.md:3` (2026-09-21) is current.",
            "`.git/logs/HEAD` shows ~60 commits since 2026-09-14 alone, including the router replacement (`20d3913`, `cfeee38`), gender inference (`59a3c83`, `e9543d4`), the context-window resolver (`a5c4e21`) and the Facebook Page work — none reflected in the five documents above.",
            "`docs/code-standards.md:139-141` still describes resources as \"registered in `components/atomic-crm/root/CRM.tsx` (8 total…)\" while `frontend/src/components/atomic-crm/root/CRM.tsx:92-94` renders them from `runtime.resources` supplied by `capabilities/static-recruitment-runtime.ts`.",
            "`AGENTS.md:63-64` requires doc updates for user-visible behaviour, setup, architecture and contracts — all of which the changes above are.",
        ],
        impact=(
            "Engineers and agents plan against a July picture of a September codebase, and the wrong "
            "resource-registration model in `docs/code-standards.md` is exactly the kind of claim that "
            "leads to a confidently wrong edit."
        ),
        fix=(
            "Backfill `TECH.md` and `docs/codebase-summary.md` now (with DOC-03), then stop "
            "hand-maintaining the fast-drifting facts: add a CI step asserting `docs/codebase-summary.md`'s "
            "migration-head string equals `alembic heads` output, and refresh the \"Last updated\" stamps "
            "in the change that touches the behaviour."
        ),
        notes="Merge with DOC-03 — same documents, same regeneration fix.",
    ),
    dict(
        id="DOC-12",
        column="QA_TESTED",
        title="Config duplication — three Makefiles, two JS lockfiles, two hook configs and rules duplicated across two trees",
        sev="medium",
        area="docs",
        labels=["documentation", "tech-debt"],
        effort="M",
        evidence_log=[
            'config duplication reduced: hooks collapsed to settings.json, docs/agent-development-kit.md records one configuration authority',
            'verified: docs/agent-development-kit.md rewritten with the hooks layer + verification section',
            'QA 2026-09-24 (orchestrator, first-hand): unit 2299 passed + ruff clean; integration 130 passed (Postgres 16 disposable DB, alembic head); frontend tsc/eslint/vitest 593 green; e2e chromium 4 and Mobile Chrome 4 green against the real backend',
        ],
        problem=(
            "Every shared concern in the build has at least two authoritative files: three Makefiles (one "
            "lowercase), two JS lockfiles for one package-manager boundary, two compose files plus Vite "
            "dev proxies, a tracked Caddy template against a generated Caddy file, two hook configs, and "
            "code-convention rules restated across `standards/` and `docs/`."
        ),
        evidence=[
            "Makefiles ×3 — `Makefile` (7.9 KB root), `backend/Makefile` (12.5 KB) and `frontend/makefile` (**lowercase**, 2.3 KB); root `deploy` shells into the other two, so one release-flow edit means three files, and `TECH.md`/`AGENTS.md` mark all three approval-gated.",
            "Lockfiles ×2 for the same boundary — `frontend/package-lock.json` (568.5 KB) and `frontend/pnpm-lock.yaml` (370.4 KB) are both tracked with `.npmrc` and `.nvmrc` present, while `TECH.md:31` says \"npm + `legacy-peer-deps`\": ~940 KB of churn and an ambiguous install path.",
            "Caddy — `backend/Caddyfile.template` is tracked while `backend/Caddyfile` is generated at deploy and mounted at `backend/docker-compose.yml:224`, so a clean `docker compose up` in `backend/` cannot mount the volume, and two docs call the generated file the real one.",
            "Rules duplicated — `standards/coding-style.md:4-5` versus `docs/code-standards.md` (15.8 KB), both presented as \"Code conventions\" by `AGENTS.md:11` and `TECH.md` §5, with the same content restated a third time in `standards/review-checklist.md`; the overlap has already produced a contradiction (virtuoso/virtua — DOC-03).",
            "Hook config ×2 — `.claude/settings.json` versus `.claude/hooks/hooks.json`, including the doubled `UserPromptSubmit` block (DOC-05).",
        ],
        impact=(
            "Every release-flow or convention change has to be made in two or three places, and the "
            "duplicates have already diverged in ways that mislead readers; the second lockfile means two "
            "different dependency resolutions can be claimed for one project."
        ),
        fix=(
            "Collapse each pair to one authoritative file with the other holding only a pointer: keep "
            "`backend/Makefile` plus a thin root delegator (delete `frontend/makefile` or make it a "
            "one-line delegator); commit one JS lockfile (`pnpm-lock.yaml` **or** `package-lock.json`, per "
            "`TECH.md:31` → npm); make `AGENTS.md:11` point at exactly one code-convention document; and "
            "delete the redundant hook manifest if `settings.json` is the live file."
        ),
        notes="Merge with DOC-05 (hooks), OPS-05 (lockfile policy) and OPS-19 (Makefile variable forwarding).",
    ),
    dict(
        id="DOC-13",
        column="QA_TESTED",
        title="frontend/public ships ~7.7 MB with the same login art committed three times",
        sev="medium",
        area="docs",
        labels=["documentation", "performance"],
        effort="S",
        evidence_log=[
            'QA 2026-09-24 (orchestrator, first-hand): unit 2299 passed + ruff clean; integration 130 passed (Postgres 16 disposable DB, alembic head); frontend tsc/eslint/vitest 593 green; e2e chromium 4 and Mobile Chrome 4 green against the real backend',
        ],
        problem=(
            "Everything under `frontend/public/` is copied verbatim into the built image and served to "
            "browsers, yet it carries ~7.7 MB of masters and duplicates — four renderings of two login "
            "screens (≈2.47 MB) and multiple sizes of the same icons — against a VitePWA cache budget of "
            "≤5 MiB."
        ),
        evidence=[
            "`login-recruiting-workspace.png` 2.0 MB + `login-recruiting-workspace.jpg` 302.4 KB + `login-recruiting-console-v2.webp` 69.7 KB + `login-mobile-workspace.jpg` 101.7 KB — four renderings of two login screens ≈ **2.47 MB**.",
            "`tinghire-icon-1024.png` 1.1 MB + `tinghire-icon-512.png` 189.5 KB + `tinghire-icon-192.png` 20.7 KB + `maskable_icon.png` 423.0 KB + `maskable_icon_x512.png` 147.4 KB, `ttsoft-logo.png` 868.8 KB, `bg.avif` 785.3 KB, `preview.png` 74.3 KB, plus `img/`, `brand/` and `appIcon/` (32 icons) — total ≈ **7.7 MB**.",
            "`frontend/Dockerfile` builds with node and serves from `nginx:1.27-alpine`, so everything under `public/` is copied verbatim into the image.",
            "`docs/codebase-summary.md:209` documents VitePWA with a ≤5 MiB cache budget — half-consumed by three copies of one hero image.",
        ],
        impact=(
            "Slower cold loads for Vietnamese mobile users on a droplet-hosted origin, and a PWA cache "
            "budget half-consumed by duplicate art."
        ),
        fix=(
            "Keep the `.webp`/`.avif` display sizes in `frontend/public/`, move masters (`*-1024.png`, "
            "`ttsoft-logo.png`, the `.png` login render) to `assets/` or a design repo outside the build "
            "path, and delete the `.jpg`/`.png`/`.webp` triplicate after confirming which are referenced."
        ),
        notes="Merge with DOC-07 — both are asset-bloat removals and should land in the same pass.",
    ),
]
