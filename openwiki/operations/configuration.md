---
type: wiki
title: "Configuration, settings, and ownership of env keys"
description: "Settings split between code constants (Zalo endpoints, EMBEDDING_DIM, DIGEST_*), Settings() env-loaded fields (DB pool, intervals, CORS, secrets), and admin-managed runtime credentials."
tags: [configuration, settings, env, secrets, db-pool, admin-managed]
sources:
  - id: openwiki-source-6dcfc1451bcbf8009d0484a9
    resource: repo://backend/app/core/config.py
  - id: openwiki-source-085098b884681cab422762c1
    resource: repo://backend/app/services/integration_settings.py
generated: { by: "claude-code", at: "2026-09-08T09:17:45.993Z" }
verified:
  - by: openwiki/0.5.0
    at: 2026-09-21T02:42:43.794Z
---

# Configuration, settings, and ownership of env keys

TingHire's configuration is split into three ownership classes. Understanding
which class owns a value prevents accidental misconfiguration and clarifies
who can change what without a deploy.

## Ownership classes

### 1. Code constants (`backend/app/core/config.py` module-level)

Values that are compile-time constants — changing them requires a code change
and a deploy. They are plain Python names, not `Settings` fields.

| Constant | Value | Why constant |
|---|---|---|
| `ZALO_BOT_API_BASE` | `https://bot-api.zaloplatforms.com` | Zalo's API base is fixed; an empty/missing URL silently 401-drops all inbound |
| `ZALO_OA_API_BASE` | `https://openapi.zalo.me` | Same — the OA API base is a Zalo-platform invariant |
| `ZALO_BOT_WEBHOOK_URL` | `https://bot.tingting.vip/webhooks/zalo/chatbot` | Registered webhook URL; must match what Zalo has on file |
| `EMBEDDING_DIM` | `3072` | Schema-pinned: `vector(3072)` in pgvector (migration 0001) and `halfvec(3072)` HNSW indexes (migrations 0014/0016). A mismatch disables ANN |
| `DIGEST_SECTION_CHARS` | `6000` | Characters per ingestion chunk |
| `DIGEST_SECTION_OVERLAP` | `400` | Overlap between adjacent chunks |
| `DIGEST_MAX_SECTIONS` | `20` | Hard cap on sections per document |
| `INGEST_JOB_TIMEOUT_SECONDS` | `3600` | Deliberately not env-tunable — bounds worst-case cost of a malicious or runaway doc |

The embedding model's output dimension must equal `EMBEDDING_DIM`. A mismatch
breaks both writes (wrong-width vector column) and ANN retrieval; the retrieval
layer gates ANN on it and warns on drift instead of silently degrading to exact
search.

### 2. Environment-loaded fields (`Settings` — `.env` / shell)

`backend/app/core/config.py` defines a `Settings(BaseSettings)` class that
loads from `.env` (dev) or the shell environment (prod). `get_settings()` is
`@lru_cache`d so every import sees the same instance.

Key groups:

**App & CORS**
- `app_env` (default `development`) — controls dev-only fallbacks (JWT secret, encryption key)
- `cors_origins` — comma-separated; `model_post_init` refuses to boot with `*` when credentials are enabled

**Database**
- `database_url` / `database_url_sync` — async (app runtime) and sync (Alembic, scripts)
- `db_pool_size`, `db_max_overflow`, `db_pool_timeout`, `db_pool_recycle`

**Redis**
- `redis_url` — RQ broker, per-chat mutex, pub/sub, Socket.IO bus

**Auth**
- `jwt_secret`, `jwt_algorithm`, `access_token_expire_minutes`, `refresh_token_expire_days`
- `integration_settings_encryption_key` — AES-GCM key for admin-managed secrets at rest

**Zalo / Facebook / LLM providers** — bootstrap/dev fallbacks; production
overrides from admin-managed `integration_settings` (see below)

**Retrieval & RAG**
- `rag_ann_enabled`, `rag_ann_candidates`, `rag_similarity_floor`, `rag_rrf_rank_constant`
- `embedding_provider`, `openrouter_embedding_model`, `embedding_dim`

**Operational**
- `bot_lock_ttl_seconds` (180s), `chat_turn_job_timeout` (60s), `reconcile_interval_seconds` (60s)
- `kb_sync_cron` — daily cron expression (UTC) for external-source sync; validated at startup via `python-crontab`

**model_post_init guards** (fail-fast at boot):
1. `jwt_secret` must not be the committed dev default when `app_env != "development"`
2. `integration_settings_encryption_key` must be set when `app_env != "development"`
3. `cors_origins` must not contain `*` (credentials are always enabled)

### 3. Admin-managed runtime credentials (`integration_settings` table)

The `IntegrationSettingsService` reads from the `integration_settings` DB table
(rows keyed by a stable string `key` with `encrypted_value`, `is_secret`,
`updated_by`, timestamps). Secrets are encrypted at rest with AES-GCM
(`IntegrationSettingsCipher`).

**Resolution order**: admin-managed DB row → env/bootstrap fallback. The
`graph.factories.build_deps` function constructs runtime configs
(`ZaloRuntimeConfig`, `MinimaxRuntimeConfig`, `OpenRouterRuntimeConfig`,
`FacebookRuntimeConfig`) from the service, so every chatbot turn uses the
admin-managed value when present.

**Encryption**: `IntegrationSettingsCipher` wraps every secret in AES-GCM with
a 12-byte random nonce. The key is `SHA-256(INTEGRATION_SETTINGS_ENCRYPTION_KEY)`,
falling back to `SHA-256(JWT_SECRET)` only in `app_env == "development"`.
Per-Page Facebook tokens use `v2:` ciphertext with AAD = page_id so a
ciphertext produced for Page A fails to decrypt under Page B.

**Admin UI**: `admin_view()` returns only `{configured, preview: '<first4>...<last4>'}`
for each secret; short values are fully masked. The admin API is gated by
`require_admin`.

**Cache eviction**: Admin updates encrypt the value, upsert the row, record an
audit row (changed keys only — never values), commit, evict the local cache
namespace, and bump the namespace version so subsequent reads decrypt fresh.
Secret-bearing caches live in `_LOCAL_SECRET_CACHE` keyed by namespace + version
+ key_prefix and never enter Redis.

## Database connection budget

The comment on `db_pool_size` / `db_max_overflow` in `config.py` spells out the
math:

```
Peak DB connections ≈ (# DB-touching processes) × (db_pool_size + db_max_overflow)
```

With the production topology (2 web + 2 worker-chatbot + 1 each for
persistence/ingest/followup/scheduler/reconcile ≈ 11 processes) at 10+10,
peak is ~220 connections. Postgres `max_connections` must be raised to ≥250
(or lower pool sizes via env on a smaller box).

`db_pool_recycle` (default 1800s = 30 min) proactively refreshes connections
before server-side idle timeouts stale them. Paired with `pool_pre_ping`
(enabled by default in SQLAlchemy 2.x), it removes the intermittent
"connection already closed" errors that plagued long-lived workers.

## HTTP client pool

`http_max_connections` (20) and `http_max_keepalive_connections` (10) size the
process-scoped `httpx.AsyncClient` pool in `app.core.http`. Conservative
defaults for the 2-vCPU droplet: enough keepalive slots to avoid handshakes on
burst, small enough to stay under the global file-descriptor budget alongside
the DB pool.

## LLM concurrency controls

Two Redis-backed semaphores throttle provider calls deployment-wide:

| Semaphore | Default | Purpose |
|---|---|---|
| `llm_concurrency_limit` | 8 | Max concurrent LLM calls across all workers |
| `embed_concurrency_limit` | 6 | Max concurrent embedding calls |

A turn that can't acquire a token within `llm_acquire_timeout_seconds` (1.5s)
raises `LLMThrottled` → sends the static `DEGRADATION_REPLY` + clears the
mutex. This fail-fast design prevents ~30s stalls and deadlock risk.
