# Deployment Guide

**Last updated:** 2026-07-26
**Production host:** `bot.tingting.vip` (DigitalOcean droplet, 2 vCPU / ~4 GB RAM)
**Stack path:** `/opt/vfic` · **Git remote:** `git@github.com:4rankng/ChatBotN8N.git` (`main`)

Deployment is **manual**, driven from a developer mac over SSH. There is **no
CI deploy to production** — `make deploy` builds + pushes both images and runs a
**blue/green** cutover over SSH (ControlMaster multiplexed). The cutover is
zero-downtime: the new color is health- + smoke-checked before Caddy is flipped
onto it, and a failed smoke gate aborts with the old color still serving.

---

## 1. Production stack — Docker Compose with a blue/green web tier

`backend/docker-compose.yml` is shipped to `/opt/vfic` and auto-loads
`/opt/vfic/.env`. Images are pulled from DockerHub:
immutable `:<git-sha>` tags. `latest` remains a registry convenience tag but is
never used by `make deploy`.

| Service | Image / base | Replicas | Role |
|---|---|---|---|
| `postgres` | `pgvector/pgvector:pg16` | 1 | Source of truth. `max_connections=150`, healthcheck `pg_isready`, volume `vfic_pgdata`. |
| `redis` | `redis:7-alpine` | 1 | RQ broker + pub/sub + LLM semaphore/cache. AOF on, 256 MB cap `allkeys-lru`, volume `vfic_redisdata`. |
| `web-blue` / `web-green` | `franknguyenvd/vfic-backend:latest` | 1 each (only **active** receives traffic) | FastAPI (uvicorn, 1 worker). Expose 8000. Volume `vfic_kb_uploads`. Healthcheck `python urllib /health`. The **active** color is tracked in `/opt/vfic/ACTIVE_COLOR`; Caddy proxies only it. The inactive color is stopped between deploys (kept for instant rollback). |
| `worker-chatbot` | `franknguyenvd/vfic-backend:latest` | **2** | RQ queue `webhook_high` only. Chatbot imports and LLM clients are warmed at boot. `stop_grace_period: 180s`; 512 MB limit per container. |
| `worker-persistence` | `franknguyenvd/vfic-backend:latest` | **1** | RQ queue `persistence_low` only. Best-effort lead/memory enrichment; isolated so it cannot delay candidate replies. 512 MB limit. |
| `worker-ingest` | `franknguyenvd/vfic-backend:latest` | 1 | RQ queue `ingest`. Mount `vfic_kb_uploads`. |
| `worker-followup` | `franknguyenvd/vfic-backend:latest` | 1 | RQ queue `followup`. Single replica (low proactive volume). |
| `scheduler` | `franknguyenvd/vfic-backend:latest` | 1 | `rqscheduler`. |
| `oa-profile-backfill` | active `franknguyenvd/vfic-backend:<git-sha>` | on demand | Profile-gated maintenance job that fills only missing Zalo OA profile names and avatars. It is not started by ordinary `docker compose up`; deploy starts it after a successful cutover. |
| `frontend` | `franknguyenvd/vfic-frontend:latest` | 1 | nginx static SPA. Expose 80. |
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
`make deploy` is the one command that handles the whole thing: release-check →
build + push both images → blue/green cutover.

### Full deploy (`make deploy`)
1. `release-check` — clean committed worktree, exactly one Alembic head, then
   backend lint/tests + integration smoke, frontend lint/typecheck/scoped
   coverage/build + desktop/mobile Playwright, and the offline golden correctness
   check. Stops before any image is pushed if a check fails.
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

### Blue/green cutover (`scripts/bg_deploy.sh`) — zero downtime at the edge
1. Pull the new backend image for the inactive web color and backend workers;
   the frontend is not part of a backend blue/green cutover.
2. Ensure postgres + redis (never force-recreate the data stores).
3. Alembic widen + `upgrade head` (additive migrations are safe for blue/green;
   see `deploy-breaking` for non-additive ones).
4. Bring up the **inactive** web color + all workers at the new tag.
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
   - `docker compose ps` shows 1 `frontend`, 2 `worker-chatbot`, 1 each of
     `worker-persistence`, `worker-ingest`, `worker-followup`, and `scheduler`
     containers running, with health checks healthy when present.
   - `web-<color>` `/health/queue` exposes queue depth, busy/total workers,
     LLM latency, recent LLM invokes, and recent Minimax 429 counters.
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

- **HEAD:** `0053_single_page_external_source_sync_state` (26 Jul 2026).
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

> Alembic stores revision IDs in `VARCHAR(32)`. Revision identifiers must stay
> within that limit; filenames may be longer.

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
| `WEB_CONCURRENCY` | uvicorn worker count (default 2). |

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
| `JWT_ALGORITHM` | `HS256`. |
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

### LLM providers
| Name | Purpose |
|---|---|
| `MINIMAX_ENABLE` | Primary provider toggle. |
| `MINIMAX_API_KEY` | MiniMax API key. |
| `MINIMAX_BASE_URL` | `https://api.minimax.io/v1`. |
| `MINIMAX_AGENT_MODEL` | `MiniMax-M2.7-highspeed`. |
| `MINIMAX_SAFETY_MODEL` | `MiniMax-M2.5-highspeed`. |
| `MINIMAX_DIGEST_MODEL` | Background KB digestion model. |
| `MINIMAX_REQUEST_TIMEOUT` | 60s. |
| `OPENROUTER_ENABLE` | Enables OpenRouter as a selectable generation provider. |
| `OPENROUTER_API_KEY` | OpenRouter API key. |
| `OPENROUTER_BASE_URL` | `https://openrouter.ai/api/v1`. |
| `OPENROUTER_AGENT_MODEL` / `OPENROUTER_SAFETY_MODEL` / `OPENROUTER_DIGEST_MODEL` | Default `deepseek/deepseek-v4-flash`. |
| `OPENROUTER_REQUEST_TIMEOUT` / `OPENROUTER_DIGEST_TIMEOUT` | 60s / 180s. |
| `CUSTOM_LLM_ENABLE` / `CUSTOM_LLM_API_KEY` / `CUSTOM_LLM_BASE_URL` / `CUSTOM_LLM_AGENT_MODEL` / `CUSTOM_LLM_SAFETY_MODEL` / `CUSTOM_LLM_FAST_MODEL` / `CUSTOM_LLM_LABEL` / `CUSTOM_LLM_REQUEST_TIMEOUT` | Third provider slot (any OpenAI-compatible endpoint, e.g. Xiaomi MiMo). Env is bootstrap fallback only — runtime prefers the settings page. |
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

### Scaling knobs (in `config.py`, env-tunable)
| Name | Default | Purpose |
|---|---|---|
| `BOT_LOCK_TTL_SECONDS` | 180 | Per-chat mutex TTL (must exceed worst-case turn). |
| `CHAT_TURN_JOB_TIMEOUT` | 60 | RQ job timeout (must be < lock TTL and reconcile grace). |
| `CHAT_QUEUE_MAX_DEPTH` | 40 | Backpressure ceiling on `webhook_high`. |
| `LLM_CONCURRENCY_LIMIT` | 0 (disabled) | Redis cross-process semaphore token count. |
| `MAX_LLM_CALLS_PER_TURN` | 6 | Agent tool-loop ceiling. |
| `EMBED_CONCURRENCY_LIMIT` | 0 (disabled) | Separate embed semaphore. |
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
[docs/DROPLET-BACKUP-RESTORE.md](./DROPLET-BACKUP-RESTORE.md) for the full
procedure. Summary of the available targets:

| Target | What it does |
|---|---|
| `make backup` | `pg_dump` prod → scp to OneDrive (timestamped `.sql.gz`). Validates non-empty. |
| `make restore` | Restore latest OneDrive backup into **local dev** DB. Drops + recreates `vfic`, `alembic stamp head`, resets all passwords to `admin123`, ensures dev admin. |
| `make backup-full` | `bash scripts/backup-droplet.sh` → bundle `/opt/vfic/.env` + streamed gzipped `pg_dump` + volume tarballs (KB uploads, Caddy TLS) + config snapshot + manifest. Output is `backups/<ts>.zip` (LOCAL only, gitignored). Embeds `restore.sh` + runbook. **Redis intentionally skipped** (orphaned-job OOM source). |
| `make restore-prod BUNDLE=backups/<bundle>` | `bash scripts/restore-droplet.sh` — rebuild on a **fresh droplet** from a bundle: preflight (SSH/Docker/free 80/443), restore `.env` + Caddyfile + compose, pull images, seed Caddy TLS + KB volumes best-effort, start postgres+redis, load SQL dump, bring up stack, verify health. Redis fresh. Alembic + `create_admin` skipped. Supports `--dry-run`. |

---

## 9. Local dev stack

`make dev` (root) → `make -C backend dev PORT=5173`.

- **Dev compose** (`backend/docker-compose.dev.yml`): Postgres+pgvector +
  Redis + Adminer only. Backend + frontend run on host for hot-reload.
  - Postgres `:5432`, Redis `:6382` (6379 belongs to sibling payroll project),
    Adminer `:8082` (8081 collides with `tuyennhanvien`). Dev Redis has no
    password.
- `make db` (backend) starts the dev stack, waits healthy, auto-creates
  `backend/.env` from `.env.example` (host rewrites: `postgres:` →
  `localhost:`, `redis://redis:6379` → `redis://localhost:6382`), runs
  `alembic upgrade head`, creates the dev admin.
- Backend: `uvicorn app.main:app --reload --port 8000`.
- Frontend: `npm run dev --port 5173 --strictPort` (Vite proxies `/api`,
  `/realtime`, `/socket.io` → `localhost:8000`).
- Dev workers: `rq worker ingest` + `rq worker webhook_high persistence_low`
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
| 5432 | Postgres (dev) |
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
