# Deployment Guide

**Last updated:** 2026-07-10
**Production host:** `bot.tingting.vip` (DigitalOcean droplet, 2 vCPU / ~4 GB RAM)
**Stack path:** `/opt/vfic` · **Git remote:** `git@github.com:4rankng/ChatBotN8N.git` (`main`)

Deployment is **manual**, driven from a developer mac over SSH. There is **no
CI deploy to production** — the `make deploy` flow orchestrates buildx push +
remote recreate over ~9 sequential SSH calls (ControlMaster multiplexed).

---

## 1. Production stack — 10-service Docker Compose

`backend/docker-compose.yml` is shipped to `/opt/vfic` and auto-loads
`/opt/vfic/.env`. Images are pulled from DockerHub:
`franknguyenvd/vfic-backend:latest` and `franknguyenvd/vfic-frontend:latest`
(also tagged `:<git-sha>`).

| Service | Image / base | Replicas | Role |
|---|---|---|---|
| `postgres` | `pgvector/pgvector:pg16` | 1 | Source of truth. `max_connections=150`, healthcheck `pg_isready`, volume `vfic_pgdata`. |
| `redis` | `redis:7-alpine` | 1 | RQ broker + pub/sub + LLM semaphore/cache. AOF on, 256 MB cap `allkeys-lru`, volume `vfic_redisdata`. |
| `web` | `franknguyenvd/vfic-backend:latest` | 1 | FastAPI (uvicorn, 1 worker, `web_concurrency`=2 default). Expose 8000. Volume `vfic_kb_uploads:/data/kb_uploads`. Healthcheck `python urllib /health`. |
| `worker-chatbot` | `franknguyenvd/vfic-backend:latest` | **1** | RQ queues `webhook_high`, `persistence_low`. `stop_grace_period: 180s` (let ≤60s turns finish on SIGTERM). Mem limit 512M. |
| `worker-ingest` | `franknguyenvd/vfic-backend:latest` | 1 | RQ queue `ingest`. Mount `vfic_kb_uploads`. |
| `worker-followup` | `franknguyenvd/vfic-backend:latest` | 1 | RQ queue `followup`. Single replica (low proactive volume). |
| `scheduler` | `franknguyenvd/vfic-backend:latest` | 1 | `rqscheduler`. |
| `frontend` | `franknguyenvd/vfic-frontend:latest` | 1 | nginx static SPA. Expose 80. |
| `adminer` | `adminer:4` | 1 | DB UI, bound to `127.0.0.1:8081` (loopback only — reach via `make adminer` SSH tunnel). |
| `caddy` | `caddy:2` | 1 | Edge. `80:80`, `443:443`. Caddyfile ro. Volumes `vfic_caddy_data`, `vfic_caddy_config`. |

**Volumes:** `vfic_pgdata`, `vfic_redisdata`, `vfic_caddy_data`,
`vfic_caddy_config`, `vfic_kb_uploads`.

---

## 2. Caddy edge routing

`backend/Caddyfile` — site `bot.tingting.vip`. `encode zstd gzip`; security
headers (HSTS 1y, `nosniff`, `Referrer-Policy`); auto-TLS Let's Encrypt
(certs in `vfic_caddy_data`).

| Path | Upstream | Notes |
|---|---|---|
| `/webhooks/*` | `web:8000` | Zalo inbound. `/webhooks/zalo/chatbot` + `/webhooks/zalo/oa`. |
| `/health` | backend JSON | Health endpoint passthrough. |
| `/api/*` | `web:8000` | REST API (`/api/v1`). |
| `/realtime/*` | `web:8000` | `flush_interval -1` (SSE unbuffered) for `/realtime/events`. |
| `/socket.io/*` | `web:8000` | WebSocket upgrade. |
| catch-all | `frontend:80` | SPA static. |

---

## 3. Deploy flow

All targets live in the root `Makefile` (delegates to `backend/Makefile`).

### Full deploy (`make deploy`)
1. `cd frontend && make push` — buildx AMD64, tag `:latest` + `:<git-sha>`, push.
2. `cd backend && make push` — same for backend image.
3. `cd backend && make deploy`:
   - SSH `mkdir -p /opt/vfic`.
   - SCP `docker-compose.yml` + `Caddyfile` to `/opt/vfic/`.
   - Run `scripts/prod-env.sh` over SSH → generates `/opt/vfic/.env` (mode
     0600) on first deploy: random `POSTGRES_PASSWORD`, `REDIS_PASSWORD`,
     `JWT_SECRET` (openssl rand), random bootstrap admin password. Third-party
     API keys left **blank** for the operator to fill. Idempotent.
   - `docker compose pull`.
   - Tear down n8n (big-bang) to free `:80`/`:443` if present.
   - `docker compose up -d postgres redis`; wait healthy (5× SSH retry).
   - `docker compose run --rm web alembic upgrade head` (5× SSH retry).
   - `docker compose run --rm web python -m scripts.create_admin --only-if-no-admins ...`
     (idempotent bootstrap admin).
   - `docker compose up -d`.
4. Operator fills third-party keys in `/opt/vfic/.env`, then
   `docker compose up -d --force-recreate web worker-chatbot worker-ingest scheduler`.
5. Flip the Zalo Chatbot webhook in the Zalo console →
   `https://bot.tingting.vip/webhooks/zalo/chatbot`.

### Fast-track backend (`make deploy-backend`)
Rebuild + push backend image → `deploy-restart`: pull `web`, apply Alembic,
recreate `web worker-chatbot worker-ingest worker-followup scheduler`. No
compose sync, no bootstrap.

### Fast-track frontend (`make deploy-frontend`)
Rebuild + push frontend image → `deploy-restart-frontend`: pull `frontend`,
recreate `frontend` only.

### Adminer (`make adminer`)
Starts `adminer` on the droplet, opens `http://localhost:18081` via an SSH
tunnel (`-N -L 18081:127.0.0.1:8081`). Ctrl-C closes the tunnel.

---

## 4. Alembic migration run

- **HEAD:** `0023_kb_versioned_ingestion` (7 Jul 2026). 23 migrations + 1
  merge head.
- **Baseline `0001`** is ~58 KB of raw `op.execute` SQL; later revisions are
  normal Alembic. `app/models/` mirrors schema but does **not** generate
  migrations.
- **Prod run** (5× SSH retry on transient refusal):
  ```bash
  ssh root@bot.tingting.vip 'cd /opt/vfic && docker compose run --rm web alembic upgrade head'
  ```
- **Local run:**
  ```bash
  cd backend && .venv/bin/python -m alembic upgrade head
  ```

> **Known issue:** two revision IDs exceed `VARCHAR(32)` —
> `091e7edc9f76_merge_0013_password_reset_otps_0013_` (49 chars) and
> `0005_remove_knowledge_approval_gate` (35 chars). See
> [project-roadmap.md](./project-roadmap.md) K-2.

---

## 5. Bootstrap admin

`backend/scripts/create_admin.py` — sync engine (psycopg), idempotent
`--only-if-no-admins` guard (prod). Local dev skips the guard.

```bash
# Prod (idempotent — runs in the deploy flow)
docker compose run --rm web python -m scripts.create_admin \
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
| `LLM_DEFAULT_PROVIDER` | Selects `minimax` or `openrouter` when both are enabled; no runtime failover occurs. |
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
docker compose exec -T web python -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8000/metrics').read().decode())"
docker compose exec -T web python -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8000/health/queue').read().decode())"
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
