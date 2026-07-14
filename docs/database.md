# Database Reference

> Database and Redis reference for the ChatBot (VFIC miniCRM) platform.
> See [`../docs/system-architecture.md`](system-architecture.md) §6 (Data layer) for runtime details,
> [`../docs/decisions/0003-postgres-pgvector.md`](decisions/0003-postgres-pgvector.md) for the Postgres+pgvector decision.

## PostgreSQL 16 + pgvector

### Connection URLs
Configured in `backend/app/core/config.py`:

| Setting | Driver | Use |
|---|---|---|
| `database_url` | `postgresql+asyncpg://` | Async engine (FastAPI, graph layer) |
| `database_url_sync` | `postgresql+psycopg://` | Sync engine (Alembic, RQ workers) |

Default (local dev): `postgresql+asyncpg://vfic:vfic@localhost:5432/vfic`

### Engine configuration (`backend/app/core/db.py`)
- `create_async_engine` with `pool_pre_ping=True`
- `async_sessionmaker` yielding `AsyncSession(expire_on_commit=False)`
- `get_db()` — FastAPI dependency (async generator with rollback-on-error)

### Pool sizing
| Setting | Value |
|---|---|
| `db_pool_size` | 10 |
| `db_max_overflow` | 10 (max 20 total connections) |
| `db_pool_timeout` | 30s |
| `db_pool_recycle` | 1800s (30 min) |
| `pool_pre_ping` | True |

## Alembic Migrations

- **Config:** `backend/alembic.ini` (note: `sqlalchemy.url` is NOT set in INI — injected from `config.py:database_url_sync` in `alembic/env.py`)
- **Env:** `backend/alembic/env.py` — imports all models via `import app.models`, sets `target_metadata = Base.metadata`
- **Versions:** `backend/alembic/versions/` — hand-written revisions with one
  historical merge (`091e`). Alembic revision IDs must not exceed 32 characters.

### Key rules
- **Migrations are hand-written.** ORM models mirror the schema but do **not** auto-generate migrations.
- **Always write migrations manually** and test locally (`alembic upgrade head` → `alembic downgrade -1` → `alembic upgrade head`).
- **Reversibility required.** Every `upgrade()` must have a working `downgrade()`.
- See [`../AGENTS.md`](../AGENTS.md) §13 — migrations require human approval.

### Commands (from `backend/`)
```bash
.venv/bin/alembic upgrade head                    # Apply all migrations
.venv/bin/alembic downgrade -1                    # Roll back one migration
.venv/bin/alembic revision -m "description"       # Create new migration
.venv/bin/alembic history                         # View migration history
.venv/bin/alembic current                         # View current revision
```

## ORM Models (21 entities, 11 files)

Path: `backend/app/models/`

| File | Entities | Purpose |
|---|---|---|
| `base.py` | `Base` (DeclarativeBase) | SQLAlchemy declarative base |
| `user.py` | `User`, `Role` (admin/recruiter/viewer) | User accounts + roles |
| `audit.py` | `AuditEvent` | Audit log |
| `company.py` | `Company`, `Project` | Companies + projects |
| `conversation.py` | `Conversation`, `ConversationMode`, `ConversationStatus`, `Message`, `MessageSender`, `DeliveryStatus`, `BotRun`, `BotRunOutcome` | Chat conversations + messages + bot run tracking |
| `lead.py` | `Lead`, `LeadStage`, `LeadScore`, `LeadEvent`, `FollowUpTask`, `FollowupStatus` | Lead CRM pipeline + follow-ups |
| `job.py` | `Job`, `JobStatus` | Job postings |
| `knowledge.py` | `KnowledgeDocument`, `KnowledgeStatus`, `KnowledgeChunk`, `KBVersion`, `KBVersionStatus`, `KBTextFile` | KB documents, chunks (with vector embeddings), versioned releases |
| `persona.py` | `Persona` | AI agent personas |
| `integration.py` | `IntegrationSetting` | Integration credentials (Zalo, OpenRouter, etc.) |
| `password_reset.py` | `PasswordResetOtp` | Password reset OTP tokens |
| `worker_feature.py` | `WorkerFeatureCatalog`, `JobFeatureValue` | Worker feature flags + job feature values |
| `ingestion_template.py` | `IngestionTemplate`, `IngestionTemplateVersion`, `IngestionTemplateAssignment`, `KBIngestionRun`, `KBIngestionFileRun`, `StructuredFact` | Declarative ingestion templates, durable runs, and facts scoped to a KB release |

### Embeddings
- `KnowledgeChunk` stores embeddings as `vector(3072)` (pgvector) — dim 3072 via OpenRouter/Gemini.
- HNSW index for ANN search (enabled when `rag_ann_enabled = true`).

### Versioned template ingestion

Knowledge ingestion can use a published, declarative template version pinned to a
`KBVersion`. A template describes record types, typed fields, natural keys, scope,
allowed source aliases, constraints, and constants; it cannot execute code, define
tools, or replace live operational resolvers. `KBTextFile` remains the source-file
occurrence for a KB release, while ingestion runs record the frozen manifest and
per-file processing state.

`StructuredFact` is release-scoped: readers must join it through
`Project.active_kb_version_id`. This makes a KB activation or rollback switch prose
chunks and generic sourced facts together. It does not supersede code-owned live
facts, such as active recruitment vacancies, stock, tracking, or ETA.

Newly materialized typed recruitment authority rows can also carry
`kb_version_id`. Their readers prefer rows from the active release and fall back
to legacy unversioned rows only when that active release has no value for the
requested scope; this prevents a release-scoped fact from being mixed with an
older one during activation or rollback.

## Redis

Redis serves multiple roles — all ephemeral (not backed up):

| Role | Usage | Key pattern |
|---|---|---|
| **RQ broker** | Job queue for 4 queues (webhook_high, persistence_low, ingest, followup) | `rq:queue:*` |
| **Cache** | General-purpose cache (preamble cache, etc.) | `cache:*` |
| **Pub/sub** | Socket.IO cross-process emit bridge (`AsyncRedisManager`) | `socketio:*` |
| **Semantic cache** | LLM response cache for non-personalized knowledge queries | `semcache:*` |
| **Presence** | Recruiter presence (who's online, viewing what) | `presence:*` |
| **LLM semaphore** | Cross-process concurrency limit for LLM/embedding calls | `llm_sem:*` |
| **Rate limiting** | Auth endpoint rate limit counters | `ratelimit:*` |
| **Token usage** | LLM token + cost accounting | `usage:*` |

### Redis safety rules
- **Redis is not backed up.** Never store critical state in Redis — if data must survive a Redis flush, it belongs in Postgres.
- **No password in local dev.** Production config in [`deployment-guide.md`](deployment-guide.md).
- Redis isolation in tests via `conftest.py:_isolate_redis` auto-use fixture (monkeypatches to no-op double).

## Backup & Restore

- **Production backup:** `make backup` — `pg_dump` from prod Postgres → OneDrive (timestamped `.sql.gz`).
- **Restore to local dev:** `make restore` — restores latest OneDrive backup into local dev DB.
- **Full droplet backup:** `make backup-full` — env + DB + KB uploads + Caddy TLS → `backups/<ts>.zip`.
- **Restore to fresh droplet:** `make restore-prod BUNDLE=<path>`.

See [`DROPLET-BACKUP-RESTORE.md`](DROPLET-BACKUP-RESTORE.md) for the full runbook.
