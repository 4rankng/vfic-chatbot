# Deployment Guide

**Last updated:** 2026-09-30
**Production host:** `bot.tingting.vip` (DigitalOcean droplet, 2 vCPU / ~4 GB RAM)
**Stack path:** `/opt/vfic` · **Git remote:** `git@github.com:4rankng/vfic-chatbot.git` (`main`)

Deployment is **manual**, driven from a developer mac over SSH. There is **no
CI deploy to production** — `make deploy` builds + pushes both images and runs a
**blue/green** cutover over SSH (ControlMaster multiplexed). The cutover is
zero-downtime: the new color is health- + smoke-checked before Caddy is flipped
onto it, and a failed smoke gate aborts with the old color still serving.

---

## 1. Production stack — Docker Compose with a blue/green web tier

`backend/docker-compose.yml` is shipped to `/opt/vfic` and auto-loads
`/opt/vfic/.env`. Images are pulled from GitHub Container Registry
(`ghcr.io/4rankng/tinghire-{be,fe}`): immutable `:<git-sha>` tags. `latest`
remains a registry convenience tag but is never used by `make deploy`.

| Service | Image / base | Replicas | Role |
|---|---|---|---|
| `postgres` | `pgvector/pgvector:pg16` | 1 | Source of truth. `max_connections=150`, healthcheck `pg_isready`, volume `vfic_pgdata`. |
| `redis` | `redis:7-alpine` | 1 | RQ broker + pub/sub + LLM semaphore/cache. AOF on, 256 MB cap `allkeys-lru`, volume `vfic_redisdata`. |
| `web-blue` / `web-green` | `ghcr.io/4rankng/tinghire-be:<git-sha>` | 1 each (only **active** receives traffic) | FastAPI (uvicorn, 2 workers since the 2026-09-28 host resize). Expose 8000. Volume `vfic_kb_uploads`. Healthcheck `python urllib /health`. The **active** color is tracked in `/opt/vfic/ACTIVE_COLOR`; Caddy proxies only it. The inactive color is stopped between deploys (kept for instant rollback). |
| `worker-chatbot` | `ghcr.io/4rankng/tinghire-be:<git-sha>` | **4** (raised from 3 by the 2026-09-28 host resize) | RQ queues `webhook_high` then `recovery` (strict priority: a recovered-turn backlog can never delay a live candidate turn). Chatbot imports and LLM clients are warmed at boot. `stop_grace_period: 180s`; 512 MB limit per container. |
| `worker-persistence` | `ghcr.io/4rankng/tinghire-be:latest` | **1** | RQ queue `persistence_low` only. Best-effort lead/memory enrichment; isolated so it cannot delay candidate replies. 512 MB limit. |
| `worker-ingest` | `ghcr.io/4rankng/tinghire-be:latest` | 1 | RQ queue `ingest` (document ingestion, KB versions, external-source syncs — the slow lane). Mount `vfic_kb_uploads`. |
| `worker-category` | `ghcr.io/4rankng/tinghire-be:<git-sha>` | 1 | RQ queue `category` only: brief-import category-revision activations (5–15s, UI-blocking). Separate worker so a multi-minute document ingest can never delay them — RQ priority orders queues but cannot preempt a running job. 256 MB limit. |
| `worker-followup` | `ghcr.io/4rankng/tinghire-be:<git-sha>` | 1 | RQ queue `followup`. Single replica (low proactive volume). |
| `worker-maintenance` | `ghcr.io/4rankng/tinghire-be:<git-sha>` | 1 | RQ queue `maintenance` (reconcile sweep + outbound dispatch ticks, split from followup by PERF-12). |
| `scheduler` | `ghcr.io/4rankng/tinghire-be:<git-sha>` | 1 | `rqscheduler`. |
| `metrics-watch` | `ghcr.io/4rankng/tinghire-be:<git-sha>` | 1 | In-stack ops-endpoint watcher: polls `/health`, `/metrics`, `/health/queue` on both colors and emits single-line JSON alerts to stdout. |
| `oa-profile-backfill` | active `ghcr.io/4rankng/tinghire-be:<git-sha>` | on demand | Profile-gated maintenance job that fills only missing Zalo OA profile names and avatars. It is not started by ordinary `docker compose up`; deploy starts it after a successful cutover. |
| `frontend` | `ghcr.io/4rankng/tinghire-fe:<git-sha>` | 1 | nginx static SPA. Expose 80. |
| `adminer` | `adminer:4` | 1 | DB UI, bound to `127.0.0.1:8081` (loopback only — reach via `make adminer` SSH tunnel). |
| `caddy` | `caddy:2` | 1 | Edge. `80:80`, `443:443`. Caddyfile ro. Volumes `vfic_caddy_data`, `vfic_caddy_config`. |

**Volumes:** `vfic_pgdata`, `vfic_redisdata`, `vfic_caddy_data`,
`vfic_caddy_config`, `vfic_kb_uploads`.

---

## 2. Caddy edge routing

`backend/Caddyfile.template` — site `bot.tingting.vip`. This is a **template**:
every upstream is `__WEB_UPSTREAM__:8000`. `scripts/flip_caddy.sh` renders it to
`/opt/vfic/Caddyfile` substituting the active color (`web-blue` or `web-green`)
and runs `caddy reload` (a live reconfiguration — <1s, no dropped connections).
The renderer replaces the file contents in place rather than renaming a new
file over the bind mount, so the running Caddy container reads the new upstream
on reload.
`encode zstd gzip`; security headers (HSTS 1y, `nosniff`, `Referrer-Policy`);
auto-TLS Let's Encrypt (certs in `vfic_caddy_data`). Do not edit
`/opt/vfic/Caddyfile` directly — regenerate it from the template.

| Path | Upstream | Notes |
|---|---|---|
| `/webhooks/*` | active `web-<color>:8000` | Zalo inbound. `/webhooks/zalo/chatbot` + `/webhooks/zalo/oa`. |
| `/health` | backend JSON | Health endpoint passthrough. |
| `/api/*` | active `web-<color>:8000` | REST API (`/api/v1`). |
| `/realtime/*` | active `web-<color>:8000` | `flush_interval -1` (SSE unbuffered) for `/realtime/events`. |
| `/socket.io/*` | active `web-<color>:8000` | WebSocket upgrade. |
| catch-all | `frontend:80` | SPA static. |

---

## 3. Deploy flow (blue/green)

All targets live in the root `Makefile` (delegates to `backend/Makefile`).
The full deploy sequence: `make release-check` (run it yourself — `make deploy`
does not chain it) → `make deploy` = build + push both images + blue/green
cutover.

### Full deploy (`make deploy`)
1. `make release-check` — the operator-run prerequisite: `make deploy` does
   not chain it (the `deploy-backend` / `deploy-frontend` fast-tracks still
   do). It verifies: a clean committed worktree, exactly one Alembic head with
   §4 below matching it, `uv lock --check`, then the scoped Pyright gate on
   `app/graph` (zero errors; `backend/pyrightconfig.json` binds the venv), the
   production-only `npm audit`, backend lint + unit tests, the two-test
   migration-reversibility walk (the roundtrip harness walks head → base
   revision → head and renders offline on its own throwaway database, ~2 min —
   this is the one gate that needs the dev Postgres up), frontend
   lint/typecheck/registry/scoped coverage/build, and the offline golden
   retrieval-correctness check (the latency SLO is not evaluated —
   a dev machine has no production telemetry). The gate is otherwise
   **unit-only** (since 2026-09-26): the rest of the backend integration suite
   and desktop/mobile Playwright remain manual lanes and are not deploy
   blockers. Every lane runs on the deploying
   machine — there is **no CI** in the release path (see K-13 in
   `docs/project-roadmap.md`). Stops before any image is pushed if a check
   fails.
2. `cd frontend && make push` — buildx AMD64, tag `:latest` + `:<git-sha>`, push.
3. `cd backend && make push` — same for the backend image (now including
   `scripts/smoke_turn.py`, which ships in the image).
4. `cd backend && make deploy`:
   - SCP `docker-compose.yml` + `Caddyfile.template` + `scripts/{bg_deploy,bg_rollback,flip_caddy}.sh` to `/opt/vfic`.
   - `scripts/prod-env.sh` → generates `/opt/vfic/.env` (idempotent).
   - `create_admin --only-if-no-admins` (idempotent bootstrap admin).
   - Hand off to `scripts/bg_deploy.sh` (below).
5. `cd backend && make deploy-restart-frontend` pulls and recreates the newly
   pushed frontend image. This is separate from the backend blue/green cutover,
   which intentionally does not pull the frontend.

### Dependency audit gate (`npm audit`)

Since 2026-09-28 the heavy gates run as three **concurrent lanes** — backend
(pyright/ruff/unit suite), frontend (audit/lint/typecheck/registry/unit/
coverage/build), data (migration walk + golden retrieval benchmark) — with any
lane failure failing the release; wall time is the slowest lane, not their sum.
The post-gate deploy then runs the OneDrive backup and both image pushes
concurrently and waits for all three before the cutover.

`npm audit --omit=dev --audit-level=high` runs in `frontend/`:
the release fails on a new high or critical advisory in a package that actually
ships. It needs registry access and fails closed if the audit endpoint is
unreachable. Dev tooling is deliberately out of scope (assessed 2026-09-27,
re-check on any lockfile refresh): `js-yaml` (dev-only transitive of `eslint`
and `shadcn`), `sharp` (not a frontend dependency at all), and `vitest` /
`@vitest/mocker` / `baseline-browser-mapping` (test tooling, absent from
`dist/`) carry standing Dependabot alerts with no fixes available, so upgrading
to chase them buys nothing. These exclusions hold only while the affected
packages stay out of `dependencies` — the moment one of them ships, the gate is
authoritative again. The four standing moderates in the production `ra-core`
chain (`decode-uri-component` → `query-string` → `ra-core` →
`ra-i18n-polyglot`, no fix available) sit below the gate's threshold. GitHub's
alert banner counts a different resolution than the committed lockfile; the
local lockfile audit is what the gate trusts.

### Blue/green cutover (`scripts/bg_deploy.sh`) — zero downtime at the edge
1. Pull the new backend image for the inactive web color and backend workers;
   the frontend is not part of a backend blue/green cutover.
2. Ensure postgres + redis (never force-recreate the data stores).
3. Pre-migration `pg_dump` (compressed custom format) to
   `/opt/vfic/pre-migration-dumps/`, keeping the newest 5 — a dump is the only
   rollback for one-directional migrations (0017's lead-stage collapse has no
   downgrade). A failed or empty dump aborts the deploy before any migration
   runs. Then Alembic widen + `upgrade head` (additive migrations are safe for
   blue/green; see `deploy-breaking` for non-additive ones). The migration
   connection is bounded — `lock_timeout=5s` fails fast when DDL queues behind a
   long-running query instead of hanging the deploy indefinitely (old colour
   keeps serving either way), and `statement_timeout` (15 min default) bounds
   runaway statements; override via `ALEMBIC_LOCK_TIMEOUT_MS` /
   `ALEMBIC_STATEMENT_TIMEOUT_MS` when a migration legitimately needs more.
4. Bring up the **inactive** web color + all workers at the new tag. Two
   classes of service are handled differently, because the workers are shared
   across colors (they are keyed to `${IMAGE_TAG}`, not to a color):
   - Services that do **not** consume `webhook_high` (the web color,
     `worker-persistence`, `worker-ingest`, `worker-category`,
     `worker-followup`, `scheduler`, `worker-maintenance`) are recreated
     outright — restarting them cannot strand an inbound turn.
   - The turn workers (`TURN_WORKERS=worker-chatbot`) are recreated **one
     replica at a time** (`rolling_recreate_service`), waiting for a healthy
     replacement before touching the next, so at least `replicas - 1` keep
     consuming `webhook_high` throughout. Recreating all three at once leaves
     accepted webhooks queued for the whole cold preload (~83 s on this host)
     even though every container reports healthy — the 2026-09-26 incident.
     The roll uses `up -d --no-recreate --scale <svc>=<n>`, which creates the
     missing replica and leaves the surviving ones untouched; mixed tags across
     replicas during a roll are intended (blue/green already runs old and new
     code concurrently, and step 3's migrations are additive).
   - A hard gate then requires at least one healthy `worker-chatbot` replica
     before the flip; a rolled worker that never registered would otherwise
     strand every accepted webhook.
   Every service whose image is pinned to `${IMAGE_TAG}` in
   `docker-compose.yml` **must** be listed in the deploy script's `WORKERS`
   variable, or it silently keeps running the previous release —
   `worker-maintenance` (the outbound dispatcher, queue `maintenance`) was
   omitted and drifted onto 38-hour-old code until 2026-09-26.
5. Wait for the new color's `/health` to go healthy.
6. **Smoke gate**: run one real bot turn on the new color
   (`scripts/smoke_turn.py`) — exercises `claim_send` (outbox INSERT),
   `record_bot_outcome`, and the realtime emit against the live service layer
   with the LLM + Zalo stubbed (free, no external calls). The smoke now proves
   the exact persisted terminal state: one BOT message, one outbound outbox row,
   `delivery_status=SENT`, matching provider message IDs, and no retained
   external error. This catches a bad image that boots and passes `/health` but
   crashes or drifts mid-turn. **Failure aborts before the flip; the old color
   keeps serving.**
7. `flip_caddy.sh <new>` renders the Caddyfile + `caddy reload` onto the new
   color (graceful live reconfig, <1s, no dropped connections).
8. `bg_deploy.sh` records `ACTIVE_COLOR`, then runs post-flip verification
   against the public edge and live containers before the old color is stopped:
   - `https://bot.tingting.vip/health` returns `{"status":"ok"}`.
   - `https://bot.tingting.vip/` returns the frontend root.
   - `Caddyfile` routes the public edge to the new `web-<color>:8000` upstream.
   - `docker compose ps` shows 1 `frontend`, 4 `worker-chatbot`, 1 each of
     `worker-persistence`, `worker-ingest`, `worker-category`,
     `worker-followup`, `scheduler`, and `worker-maintenance` containers
     running, with health checks healthy when present.
   - `web-<color>` `/health/queue` exposes queue depth, busy/total workers,
     LLM latency, recent LLM invokes, and recent Minimax 429 counters.
   - **Turn-pipeline gate**: `python -m scripts.turn_pipeline_check` inside the
     active color (`scripts/turn_pipeline_check.py`) asserts the bot is actually
     *answering*, not merely running — at least one live consumer registered on
     `webhook_high`, no `BOT`-mode conversation waiting for a reply after its
     newest inbound (`--window`, default 300 s; in-flight turns are excluded via
     open `bot_runs`), and no `PENDING` outbound row older than `--stale-after`
     (default 120 s). `/health/queue` proves workers exist; this proves work is
     draining. Self-test: `--min-consumers 999` MUST exit 1.
   Failure on a non-inaugural deploy rolls back to `PREV_COLOR`/`PREV_TAG`.
   Inaugural failure has no prior color to restore, so `web-<color>` stays up
   and operator intervention is required.
9. Stop the old color (kept stopped, not removed → instant rollback).
10. Start the dedicated `oa-profile-backfill` maintenance container. This is
    post-cutover and non-fatal to the serving deployment; its status and output
    remain inspectable independently of either web color.

State files in `/opt/vfic`: `ACTIVE_COLOR`, `PREV_COLOR`, `PREV_TAG`.
Inaugural deploy (no `ACTIVE_COLOR` yet): `blue` is brought up first, Caddy
flipped to it, then the legacy single-`web` container is removed.

### Rollback (`make rollback`)
Revives `PREV_COLOR` at `PREV_TAG`, recreates the workers to match, and verifies
the restored tag, Caddy route, public `/health`, frontend root, exact worker
counts, and queue health before any state swap. Only after those checks pass does
it flip Caddy back (~1s, no rebuild), stop the demoted color, and swap
ACTIVE↔PREV so rollback is reversible. It first stops any running OA profile
maintenance container so code from the rejected image cannot continue writing
after the rollback. If verification fails, rollback aborts before the swap and
leaves both colors and state files unchanged.

### Status (`make deploy-status`)
Prints `ACTIVE_COLOR`, `PREV_COLOR`@`PREV_TAG`, and `docker compose ps`.

### OA profile maintenance backfill

Each successful backend cutover starts a dedicated, resumable sweep for Zalo OA
contacts that still lack a display name, contact avatar, or lead avatar. The
runner processes bounded keyset pages, retries each profile a limited number of
times, and uses a PostgreSQL advisory lock so two sweeps cannot overlap. It
updates only fields that remain blank at write time, preserving concurrent
user/admin changes. Database eligibility is the resume checkpoint, so a later
run naturally skips completed profiles. Maintenance lookups run with
`force_lookup`, so the Redis `done` marker cannot suppress a DB-eligible rerun;
Redis still enforces the per-profile lock while the PostgreSQL advisory lock
keeps sweeps from overlapping.

Identities that Zalo states can never be enriched — `-201 user_id is not
valid` (the user unfollowed or the id is dead) or a valid response whose name
and avatar are both empty — get a Redis terminal marker (same TTL as the done
marker). Sweeps skip terminally marked identities without calling Zalo and
exclude them from `remaining`, so the sweep converges and the maintenance exit
code stops failing on permanently unreachable contacts. The marker expires, so
a user who re-follows or adds profile data is retried after the TTL.

```bash
make -C backend profile-backfill-status  # container state, exit code, timestamps
make -C backend profile-backfill-logs    # structured batch/final progress
make -C backend profile-backfill-run     # explicitly start/resume using active tag
```

Exit `0` means the requested sweep completed (or reached an explicit limit),
`2` means a full run left records incomplete, and `3` means another sweep held
the advisory lock. Candidate identifiers are not written to progress logs.

### Breaking-migration deploy (`make deploy-breaking`)
For a **non-additive** migration that old + new code cannot both run against:
drains both colors, migrates, brings up `web-blue` on the new schema, flips to
it. Accepts brief downtime — use only when the additive-migration assumption
fails.

### Fast-track backend (`make deploy-backend`)
Rebuild + push backend image → `deploy-restart` (also blue/green: re-syncs the
compose file and deploy scripts, then runs `bg_deploy.sh`). It skips bootstrap.

### Fast-track frontend (`make deploy-frontend`)
Rebuild + push frontend image → `deploy-restart-frontend`: pull + recreate
`frontend` only (single-replica SPA, unaffected by the blue/green web tier).

### Adminer (`make adminer`)
Starts `adminer` on the droplet, opens `http://localhost:18081` via an SSH
tunnel (`-N -L 18081:127.0.0.1:8081`). Ctrl-C closes the tunnel.

---

## 4. Alembic migration run

- **HEAD:** `0061_project_coordinates` (2 Oct 2026). This line is
  grepped by the `release-check` docs-drift gate against the live
  `alembic heads` value, so a new migration that does not update it blocks the
  release. `0061` adds the geo-distance columns on `projects`
  (`extracted_address`, `latitude`, `longitude`) that let the catalog tool
  report `distance_km` for "dự án nào gần nhà"; all three are nullable with no
  backfill, so old and new code run against either schema. Preceding `0060`
  dropped the retired per-run decision-trace column; `0059` renamed category
  revision source to `source_markdown`; `0058` adds the deployment-wide
  `tingting_hotline` integration setting and seeds the approved hotline value so
  TingTing OA escalations end with a real contact line; the value stays editable
  from the integrations settings. `0057` drops the unused
  `match_memories(vector, integer, jsonb)` overload so the memories retrieval
  path resolves to the `halfvec` signature and uses
  `memories_embedding_halfvec_hnsw_idx`.
- **Baseline `0001`** is ~58 KB of raw `op.execute` SQL; later revisions are
  normal Alembic. `app/models/` mirrors schema but does **not** generate
  migrations.
- **Prod run** (5× SSH retry on transient refusal):
  ```bash
  ssh root@bot.tingting.vip 'cd /opt/vfic && docker compose run --rm web-$(cat ACTIVE_COLOR) alembic upgrade head'
  ```
- **Local run:**
  ```bash
  cd backend && .venv/bin/python -m alembic upgrade head
  ```

> Alembic creates `alembic_version.version_num` as `VARCHAR(32)`; this repo
> widens it to `VARCHAR(128)` (idempotently, via
> `backend/scripts/widen_alembic_version.py` before `alembic upgrade head`, and
> by migration `0001` on fresh databases) so the descriptive revision IDs fit.
> Keep IDs under 128 characters; filenames may be longer.

---

## 5. Bootstrap admin

`backend/scripts/create_admin.py` — sync engine (psycopg), idempotent
`--only-if-no-admins` guard (prod). Local dev skips the guard.

```bash
# Prod (idempotent — runs in the deploy flow)
docker compose run --rm web-$(cat ACTIVE_COLOR) python -m scripts.create_admin \
  --only-if-no-admins --email "$VFIC_BOOTSTRAP_ADMIN_EMAIL" \
  --password "$VFIC_BOOTSTRAP_ADMIN_PASSWORD" --full-name "VFIC Admin" --role admin

# Local dev
cd backend && .venv/bin/python -m scripts.create_admin \
  --email admin@vfic.dev --password admin123 --full-name "Dev Admin" --role admin
```

> Prod bootstrap admin email is `admin@vfic.vn`. Dev admin is
> `admin@vfic.dev` / `admin123`.

---

## 6. Env var reference (NAMES + purpose only — never commit values)

Sourced from `backend/.env.example` (committed template) and
`app/core/config.py`. Prod `/opt/vfic/.env` is generated by
`scripts/prod-env.sh` (mode 0600).

### App
| Name | Purpose |
|---|---|
| `APP_ENV` | `development` (default) or `production`. Gates boot-time safety checks. |
| `CORS_ORIGINS` | Comma-separated explicit origins (no `*` — credentials enabled). |
| `WEB_CONCURRENCY` | Not read by the web entrypoint: the image pins two uvicorn workers (Dockerfile CMD; raised from one by the 2026-09-28 resize to 2 vCPU / 4 GB — the old 1.9 GiB host pinned one because a second worker doubled cold-boot RSS and widened the listener gap). |

### Database
| Name | Purpose |
|---|---|
| `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB` | Postgres container creds. `POSTGRES_PASSWORD` is required (no default). |
| `DATABASE_URL` | Async URL (`postgresql+asyncpg://...`). |
| `DATABASE_URL_SYNC` | Sync URL (`postgresql+psycopg://...`) for Alembic + scripts. |

### Redis
| Name | Purpose |
|---|---|
| `REDIS_PASSWORD` | Required in prod (compose enforces). Dev has none. |
| `REDIS_URL` | `redis://[:password@]host:port/0`. |

### Auth
| Name | Purpose |
|---|---|
| `JWT_SECRET` | HS256 signing secret. Must differ from the committed dev default outside dev. |
| `JWT_ALGORITHM` | `HS256` (allowlisted: HS256/384/512 — any other value refuses to boot). |
| `JWT_ISSUER` / `JWT_AUDIENCE` | `tingting-api`. Minted on issue and required on decode. |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | 60. |
| `REFRESH_TOKEN_EXPIRE_DAYS` | 14 (rotated on each refresh). |
| `PASSWORD_RESET_OTP_TTL_MINUTES` | 10. |
| `PASSWORD_RESET_OTP_ATTEMPT_LIMIT` | 5. |
| `RESEND_API_KEY` | Transactional email (password reset). |
| `INTEGRATION_SETTINGS_ENCRYPTION_KEY` | Server-side key for admin-managed integration secrets at rest. Required outside dev. |
| `VFIC_BOOTSTRAP_ADMIN_EMAIL` / `VFIC_BOOTSTRAP_ADMIN_PASSWORD` | First-deploy admin bootstrap. |

### Zalo
| Name | Purpose |
|---|---|
| `ZALO_BOT_TOKEN` | Bot Platform token (rides in URL path `/bot{TOKEN}/...`). |
| `ZALO_BOT_WEBHOOK_SECRET` | Verifies `X-Bot-Api-Secret-Token`. |
| `ZALO_BOT_API_BASE` | `https://bot-api.zaloplatforms.com` (code constant). |
| `ZALO_BOT_REQUEST_TIMEOUT` | 30s default. |
| `ZALO_BOT_WEBHOOK_URL` | Registered webhook URL (self-tests / status). |
| `ZALO_OA_APP_ID` / `ZALO_OA_SECRET_KEY` / `ZALO_OA_ACCESS_TOKEN` | Official Account bootstrap/dev fallbacks. Runtime prefers admin-managed values. |

### Request limits and hosts
| Name | Purpose |
|---|---|
| `ALLOWED_HOSTS` | Comma-separated `Host` allowlist enforced by `TrustedHostMiddleware`. Default `bot.tingting.vip,localhost,127.0.0.1`. `*` refuses to boot. |
| `RATELIMIT_WEBHOOK_LIMIT` / `RATELIMIT_WEBHOOK_WINDOW_SECONDS` | Per-client-IP cap on the inbound webhook POSTs (default 120 / 60s). Fail-open: a Redis hiccup never drops candidate messages. |
| `RATELIMIT_LLM_LIMIT` / `RATELIMIT_LLM_WINDOW_SECONDS` | Per-user cap on `/jobs/search`, `/rag/test`, `/web-chat-turn`, `/assist` and `/chatops-actions/*` (default 30 / 60s). |
| `RATELIMIT_LLM_FAIL_CLOSED` | `false` by default; `true` denies the LLM routes with 429 when Redis cannot verify the budget instead of admitting them. |

### LLM providers
| Name | Purpose |
|---|---|
| `MINIMAX_ENABLE` | Primary provider toggle. |
| `MINIMAX_API_KEY` | MiniMax API key. |
| `MINIMAX_BASE_URL` | `https://api.minimax.io/v1`. |
| `MINIMAX_AGENT_MODEL` | `MiniMax-M3.1-Flash-Preview`. |
| `MINIMAX_EXTRACTOR_MODEL` | `MiniMax-M2.5-highspeed`. Model for post-reply candidate extraction. |
| `MINIMAX_DIGEST_MODEL` | Background KB digestion model. |
| `MINIMAX_REQUEST_TIMEOUT` | 60s. |
| `OPENROUTER_ENABLE` | Enables OpenRouter as a selectable generation provider. |
| `OPENROUTER_API_KEY` | OpenRouter API key. |
| `OPENROUTER_BASE_URL` | `https://openrouter.ai/api/v1`. |
| `OPENROUTER_AGENT_MODEL` / `OPENROUTER_EXTRACTOR_MODEL` / `OPENROUTER_DIGEST_MODEL` | Default `deepseek/deepseek-v4.1-flash`. The KB digest lane (document digestion + any-txt category mapping) prefers OpenRouter. |
| `OPENROUTER_REQUEST_TIMEOUT` / `OPENROUTER_DIGEST_TIMEOUT` | 60s / 180s. |
| `CUSTOM_LLM_ENABLE` / `CUSTOM_LLM_API_KEY` / `CUSTOM_LLM_BASE_URL` / `CUSTOM_LLM_AGENT_MODEL` / `CUSTOM_LLM_FAST_MODEL` / `CUSTOM_LLM_LABEL` / `CUSTOM_LLM_REQUEST_TIMEOUT` | Third provider slot (any OpenAI-compatible endpoint, e.g. Xiaomi MiMo). Env is bootstrap fallback only — runtime prefers the settings page. |
| `LLM_DEFAULT_PROVIDER` | `minimax` / `openrouter` / `custom` — where a turn starts. On quota or rate-limit exhaustion the turn fails over to the next enabled provider; only when every enabled provider is exhausted does the turn get suppressed (logged for engineers, no customer message). |
| `GEMINI_API_KEY` | Embedding fallback only. |
| `GEMINI_EMBEDDING_MODEL` | `gemini-embedding-2`. |
| `EMBEDDING_DIM` | 3072 (OpenRouter text-embedding-3-large). |

### Knowledge pipeline
| Name | Purpose |
|---|---|
| `KB_STORAGE_PATH` | `/data/kb_uploads`. |
| `DIGEST_SECTION_CHARS` / `DIGEST_MAX_SECTIONS` | Chunking policy (code constants). |
| `INGEST_JOB_TIMEOUT_SECONDS` | 3600s. |

### Cache
| Name | Purpose |
|---|---|
| `DASHBOARD_CACHE_ENABLED` / `DASHBOARD_CACHE_TTL_SECONDS` | Dashboard metrics cache (30s default). |

### Geocoding (geo-distance "dự án nào gần nhà")
| Name | Purpose |
|---|---|
| `GEOCODER_ENABLED` | Default `true`. Off → every lookup is a cached miss and the catalog returns no `distance_km`. |
| `GEOCODER_BASE_URL` | Default the public Nominatim instance. Repoint at a self-hosted Nominatim (or any Nominatim-compatible endpoint) for better Vietnamese coverage; no code change. |
| `GEOCODER_USER_AGENT` | Descriptive UA required by the provider's usage policy. |
| `GEOCODER_TIMEOUT_SECONDS` | 3s per attempt; a timeout is a miss. |
| `GEOCODER_CACHE_TTL_SECONDS` / `GEOCODER_NEGATIVE_TTL_SECONDS` | 30 days for a hit / 6 hours for a miss (Redis, key version `geo:geocode:v2:`). |
| `GEOCODER_MIN_INTERVAL_SECONDS` | 1.0 — the provider policy floor, enforced process-wide. |

All seven have code defaults, so a deployment whose `/opt/vfic/.env` predates
this feature needs no env change.

### Scaling knobs (in `config.py`, env-tunable)
| Name | Default | Purpose |
|---|---|---|
| `BOT_LOCK_TTL_SECONDS` | 180 | Per-chat mutex TTL (must exceed worst-case turn). |
| `CHAT_TURN_JOB_TIMEOUT` | 60 | RQ job timeout (must be < lock TTL and reconcile grace). |
| `CHAT_QUEUE_MAX_DEPTH` | 40 | Backpressure ceiling on `webhook_high` and on the `recovery` queue. |
| `LLM_CONCURRENCY_LIMIT` | 8 | Redis cross-process semaphore token count. |
| `MAX_LLM_CALLS_PER_TURN` | 6 | Agent tool-loop ceiling. |
| `EMBED_CONCURRENCY_LIMIT` | 6 | Separate embed semaphore. |
| `RECONCILE_INTERVAL_SECONDS` / `RECONCILE_GRACE_SECONDS` / `RECONCILE_MAX_AGE_SECONDS` / `RECONCILE_BATCH_SIZE` | 60 / 120 / 86400 / 50 | Reconcile sweep tuning. |
| `RAG_ANN_ENABLED` / `RAG_ANN_CANDIDATES` | True / 200 | HNSW candidate generation. |
| `RAG_CACHE_ENABLED` / `RAG_RESULT_CACHE_TTL_SECONDS` | True / 300 | Retrieval result cache. |
| `EMBEDDING_CACHE_TTL_SECONDS` | 86400 | Embedding cache. |

---

## 7. Health & metrics

| Endpoint | Auth | Returns |
|---|---|---|
| `GET /health` | none | `{"status":"ok","env":...}` |
| `GET /metrics` | none (internal) | RQ queue depths (4 queues), worker count, 7 reconcile canary counters. |
| `GET /health/queue` | none (internal) | Chat-path: queue depth, LLM latency (`_RKEY_INVOKE_MS`), 429 rate (`_RKEY_429`), fallback count, busy/total workers. |
| `GET /api/v1/admin/performance` | admin | Stage percentiles, webhook-to-send SLO, intent and LLM/tool-call diagnostics, slow turns. |

Verify after deploy:
```bash
curl -s https://bot.tingting.vip/health
docker compose exec -T web-$(cat ACTIVE_COLOR) python -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8000/metrics').read().decode())"
docker compose exec -T web-$(cat ACTIVE_COLOR) python -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8000/health/queue').read().decode())"
```

---

## 8. Backup & restore

**Do not duplicate** the finished runbook — see
[docs/ops/droplet-backup-restore.md](./droplet-backup-restore.md for the full
procedure. Summary of the available targets:

| Target | What it does |
|---|---|
| `make backup` | `pg_dump` prod (custom format) → OneDrive (timestamped `.dump`) **plus `/opt/vfic/.env`** (timestamped `vfic_env_<ts>.env`, mode 0600) so the credential-encryption key always travels with the dump. Warns when the `.env` has no `INTEGRATION_SETTINGS_ENCRYPTION_KEY`. Keeps the newest 10 dumps; each `vfic_env_*.env` is deleted together with its dump pair (an env copy holds prod secrets, so an orphan whose dump was pruned is removed, not kept — an old env copy is only findable while its dump survives). |
| `make restore` | Restore latest OneDrive backup into **local dev** DB. Fails *before* touching the DB when the backup's sealing key differs from `backend/.env` (`ALLOW_KEY_MISMATCH=1` acknowledges explicitly); warns when the backup predates `.env` snapshots. Loads with `ON_ERROR_STOP`, `alembic stamp head`, optional password reset (prompt; `FORCE=1`), then verifies sealed integration rows decrypt (`scripts/verify_integration_secrets.py`). |
| `make backup-full` | `bash scripts/backup-droplet.sh` → bundle `/opt/vfic/.env` + streamed gzipped `pg_dump` + volume tarballs (KB uploads, Caddy TLS) + config snapshot (compose, `Caddyfile.template`, `prod-env.sh`, **and the rendered `/opt/vfic/Caddyfile`**) + manifests (git HEAD, **active colour, running image tag, alembic revision**, images, volume sizes). Refuses to produce a bundle whose `.env` carries no sealing key at all. Output is `backups/<ts>.zip` (LOCAL only, gitignored). Embeds `restore.sh` + runbook. **Redis intentionally skipped** (orphaned-job OOM source). |
| `make restore-prod BUNDLE=backups/<bundle>` | `bash scripts/restore-droplet.sh` — rebuild on a **fresh droplet** from a bundle: preflight (SSH/Docker/free 80/443), restore `.env` + compose + edge config (rendered Caddyfile, or the template rendered with the recorded colour), write `ACTIVE_COLOR`/`PREV_COLOR`/`PREV_TAG`, pull images **at the tag recorded in the bundle** (`--tag` overrides; refuses `latest`/unknown), seed Caddy TLS + KB volumes best-effort, start postgres+redis, load SQL dump, run `widen_alembic_version` + `alembic upgrade head` **and assert the restored revision equals the pinned image's head**, bring up the stack, verify the running tag + container `/health` + that sealed integration rows decrypt. Redis fresh. `create_admin` skipped (dump has admins). Supports `--dry-run`. |

---

## 9. Local dev stack

`make dev` (root) → `make -C backend dev PORT=5173`.

- **Dev compose** (`backend/docker-compose.dev.yml`): Postgres+pgvector +
  Redis + Adminer only. Backend + frontend run on host for hot-reload.
  - Postgres `:5443` (5432 belongs to the kiosk-app project's postgres),
    Redis `:6382` (6379 belongs to sibling payroll project),
    Adminer `:8082` (8081 collides with `tuyennhanvien`). Dev Redis has no
    password.
- `make db` (backend) starts the dev stack, waits healthy, auto-creates
  `backend/.env` from `.env.example` (host rewrites: `postgres:` →
  `localhost:5443`, `redis://redis:6379` → `redis://localhost:6382`), runs
  `alembic upgrade head`, creates the dev admin.
- Backend: `uvicorn app.main:app --reload --port 8000`.
- Frontend: `npm run dev --port 5173 --strictPort` (Vite proxies `/api`,
  `/realtime`, `/socket.io` → `localhost:8000`).
- Dev workers: `rq worker ingest` + `rq worker webhook_high recovery persistence_low`
  (production `worker-chatbot` consumes `webhook_high recovery`; live turns are
  drained before recovered ones in both)
  as `SimpleWorker` on host.
- Zalo mock: `mock_servers/zalo_mock.py` on `:8788`. `make dev` exports
  `ZALO_BOT_API_BASE` + `ZALO_BOT_TOKEN` so outbound Zalo traffic is captured
  locally, never sent to real Zalo.
- Login: `admin@vfic.dev` / `admin123`. DB UI: `http://localhost:8082`.

### Ports
| Port | Service |
|---|---|
| 5173 | Frontend (Vite) |
| 8000 | Backend (uvicorn) |
| 5443 | Postgres (dev) — **not** 5432 (kiosk-app's postgres) |
| 6382 | Redis (dev) — **not** 6379 (payroll) |
| 8082 | Adminer (dev) |
| 8788 | Zalo mock (dev) |
| 18081 | Adminer SSH tunnel (prod) |

---

## 10. Security posture

### Boot-time safety checks
`Settings.model_post_init` refuses to boot outside `development` when:
1. `JWT_SECRET` equals the committed default (`dev-only-change-me-...`).
2. `INTEGRATION_SETTINGS_ENCRYPTION_KEY` is unset.
3. `CORS_ORIGINS` contains `*` (credentials are enabled — both a browser
   rejection and a credential-leaking misconfig).

### Secrets at rest
- Admin-managed integration credentials (Zalo, MiniMax, OpenRouter) are
  encrypted at rest in `integration_settings` using
  `INTEGRATION_SETTINGS_ENCRYPTION_KEY`.
- Runtime resolves them via `IntegrationSettingsService(db).resolve_*()`,
  falling back to env bootstrap values in dev only.
- `/opt/vfic/.env` is generated mode `0600` by `scripts/prod-env.sh`.

### The sealing key is DR-critical
`INTEGRATION_SETTINGS_ENCRYPTION_KEY` is the one secret whose loss silently
destroys data: every `integration_settings` row is AES-GCM-sealed under it, and
a dump restored without the matching key yields rows that raise `InvalidTag`,
get skipped with a warning, and fall back to env values — the stack looks
healthy while the stored credentials are gone. `JWT_SECRET` is only the
legacy/dev fallback; a value sealed under the fallback reopens only under that
same secret, so rotating `JWT_SECRET` re-breaks every sealed row.

Both backup paths therefore carry `/opt/vfic/.env` (`make backup`'s timestamped
snapshot and `make backup-full`'s bundle, both mode 0600), a full-droplet bundle
without any sealing key is refused outright, and every restore verifies sealed
rows actually decrypt (`backend/scripts/verify_integration_secrets.py`, run in
dev after `make restore` and inside the pinned image by `restore-droplet.sh`).
Store the key in a password manager separate from the droplet and the backup
files, and never rotate it without re-sealing stored credentials.

### Redis is not backed up (by design)
Redis holds only ephemeral state: RQ broker, per-chat locks, pub/sub, rate
limit counters, caches. Including it in backups reintroduces the orphaned-job
OOM source. `scripts/backup-droplet.sh` skips it explicitly; `restore-droplet.sh`
starts a fresh Redis.

### Auth
- JWT HS256; access 60 min, refresh 14 day (rotated). `token_version` claim
  enables revocation without a denylist (bumped on password change).
- Argon2 password hashing; crypto on worker threads via `asyncio.to_thread`.
- Rate limits: login 10/60s/IP, forgot-password 5/300s/IP + 3/900s/email.
- Password reset OTP TTL 10 min, attempt limit 5.

### Network surface
- Caddy is the only public edge (`:80`, `:443`).
- Adminer is bound to `127.0.0.1:8081` on the droplet — reachable only via
  the `make adminer` SSH tunnel.
- Postgres + Redis are not exposed publicly (compose `expose`, not `ports`,
  for `web`/`worker-*`/`postgres`/`redis`).
- `/metrics` and `/health/queue` are unauthenticated — rely on network-level
  restriction (do not expose them publicly; Caddy only routes `/health`,
  `/api/*`, `/realtime/*`, `/socket.io/*`, `/webhooks/*`).

### No external APM
No Sentry/Datadog/OpenTelemetry. Observability = structured JSON logs to
stdout + `/metrics` + `/health/queue` + Caddy access logs.

## Ops alerting (OPS-04, OPS-06)

Nothing external scrapes this deployment, so the droplet tells itself when it is
about to hurt: `scripts/ops-alerts.sh` checks disk usage (warn >80%, fail >95%),
reclaimable Docker space, the live container's `/metrics` (queue depth vs
`CHAT_QUEUE_MAX_DEPTH`, every worker busy, the two reconcile counters that only
rise) and `GET /health` on the edge.

```cron
* * * * * root /opt/vfic/scripts/ops-alerts.sh 2>> /var/log/vfic-alerts.log
```

Installed on the droplet as `/etc/cron.d/vfic-ops-alerts` (2026-09-28; the
script had shipped but the schedule had never been installed).

Ship the script with the config snapshot the deploy pushes to `/opt/vfic/`, and
read `/var/log/vfic-alerts.log` (or forward it wherever you already read logs).
Container logs are also bounded now: every service carries the compose
`x-logging` anchor (`json-file`, 10 MB × 3 files), so a chatty container cannot
fill the volume and stop Postgres writing WAL.

An external uptime check on `https://bot.tingting.vip/health` is still worth
adding — it is the one thing this script cannot see from inside the droplet.
