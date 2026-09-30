# Database Reference

> Database and Redis reference for the ChatBot (VFIC miniCRM) platform.
> See [`../docs/system-architecture.md`](system-architecture.md) §6 (Data layer) for runtime details,
> [`../docs/decisions/0003-postgres-pgvector.md`](../decisions/0003-postgres-pgvector.md) for the Postgres+pgvector decision.

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
- Migrations require human approval before they land on `main`.

### Commands (from `backend/`)
```bash
.venv/bin/alembic upgrade head                    # Apply all migrations
.venv/bin/alembic downgrade -1                    # Roll back one migration
.venv/bin/alembic revision -m "description"       # Create new migration
.venv/bin/alembic history                         # View migration history
.venv/bin/alembic current                         # View current revision
```

## ORM model modules

Path: `backend/app/models/`

| File | Entities | Purpose |
|---|---|---|
| `base.py` | `Base` (DeclarativeBase) | SQLAlchemy declarative base |
| `user.py` | `User`, `Role` (admin/recruiter/viewer) | User accounts + roles |
| `audit.py` | `AuditEvent` | Audit log |
| `case_workflow.py` | `CaseWorkflowVersion`, `CaseWorkflowStage`, `CaseWorkflowTransition`, `CaseTagDefinition` | Immutable administrator-authored generic workflows |
| `contact.py` | `Contact`, `ContactChannelIdentity` | Typed people and account-scoped channel identity authority |
| `case.py` | `Case`, `CaseTagAssignment`, `CaseNote`, `CaseFollowup` | Generic workflow-pinned operational Cases |
| `company.py` | `Company`, `Project` | Companies + projects |
| `conversation.py` | `Conversation`, `ConversationMode`, `ConversationStatus`, `Message`, `MessageSender`, `DeliveryStatus`, `BotRun`, `BotRunOutcome` | Chat conversations + messages + bot run tracking |
| `lead.py` | `Lead`, `LeadStage`, `LeadScore`, `LeadEvent`, `FollowUpTask`, `FollowupStatus` | Lead CRM pipeline + follow-ups |
| `job.py` | `Job`, `JobStatus` | Job postings |
| `knowledge.py` | `KnowledgeDocument`, `KnowledgeStatus`, `KnowledgeChunk`, `KBVersion`, `KBVersionStatus`, `KBTextFile` | KB documents, chunks (with vector embeddings), versioned releases |
| `persona.py` | `Persona` | AI agent personas |
| `integration.py` | `IntegrationSetting` | Integration credentials (Zalo, OpenRouter, etc.) |
| `installation.py` | `InstallationManifestRevision`, `InstallationManifestValidation`, `InstallationState`, `InstallationSetupDraft` | Immutable installation authority plus the mutable admin setup workspace |
| `password_reset.py` | `PasswordResetOtp` | Password reset OTP tokens |
| `worker_feature.py` | `WorkerFeatureCatalog`, `JobFeatureValue` | Worker feature flags + job feature values |
| `ingestion_template.py` | `IngestionTemplate`, `IngestionTemplateVersion`, `IngestionTemplateAssignment`, `KBIngestionRun`, `KBIngestionFileRun`, `StructuredFact` | Declarative ingestion templates, durable runs, and facts scoped to a KB release |

### Embeddings
- `KnowledgeChunk` stores embeddings as `vector(3072)` (pgvector) — dim 3072 via OpenRouter/Gemini.
- HNSW index for ANN search (enabled when `rag_ann_enabled = true`).

### Category revisions

`KnowledgeCategoryRevision` stores its raw authoring content in
`source_markdown` (renamed from `source_yaml` by migration
`0059_category_markdown_source`, which also converted stored YAML rows to
Category Markdown v1). Activated revisions are republished as
`KnowledgeDocument` rows with `source = 'category_markdown'` and
`mime_type = 'text/markdown'`.

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

### Installation configuration authority

Customer identity, industry-pack selection, terminology, workflow, persona and
template references, provider policy, and authentication policy are stored in
PostgreSQL rather than business environment variables or browser storage.

- `installation_setup_drafts` is a singleton mutable authoring row. It starts
  absent, contains only strict partial admin input and encrypted-integration
  references, and uses `lock_version` to reject stale Settings writes.
- Finalization validates the complete draft and appends an immutable
  `installation_manifest_revisions` row plus checksum-pinned
  `installation_manifest_validations` evidence in one transaction.
- `installation_state` owns lifecycle pointers and the monotonic authority
  generation. A validated revision is not active authority.
- Migrations `0042` and `0043` insert no customer, industry, persona, template,
  credential, or sample-data rows. `0043` adds the setup draft and explicit
  authentication-policy evidence needed by the setup flow.
- Migration `0044` adds nullable immutable workflow-version/checksum pins to
  revisions and validation evidence. New setup finalization requires an
  explicit matching pair; historical null-pinned revisions remain readable but
  are not future activation authority.
- Integration secrets remain encrypted in `integration_settings`; setup drafts
  store logical references only and reject secret-shaped values.

### Dormant generic workflow, Contact, and Case kernel (`0044`)

Migration `0044_generic_contact_case_kernel` is additive DDL with no business
row seeds and no inferred Lead/Conversation backfill:

- `case_workflow_versions`, stages, transitions, and tag definitions form one
  normalized immutable version. A canonical checksum covers the published
  definition, and database triggers reject later parent/child insert, update,
  or delete operations that would reinterpret pinned Cases.
- `contacts` contains only typed nullable profile fields and an optimistic
  version; V1 deliberately has no generic Contact attribute JSON.
  `contact_channel_identities` owns the unique configured authority tuple
  `(provider, account_key, external_id)` and does not invent an account key.
- `cases` pins workflow version/checksum and current stage, with closed
  `OPEN|CLOSED|CANCELLED` lifecycle, assignment, optimistic version, and a
  bounded Case-only attribute object validated against the pinned schema.
  Tags, append-only notes, and typed follow-ups use dedicated tables.
- `conversations.contact_id` and `channel_identity_id` are nullable for legacy
  compatibility. Foreign keys and a check prove that a linked channel identity
  belongs to the linked Contact; a partial unique index permits one V1
  Conversation per channel identity. No `conversation.case_id` was added.

The downgrade refuses while any generic-kernel row, Conversation identity link,
or installation workflow pin/evidence exists. Disposable PostgreSQL tests cover
the empty `0043 -> 0044 -> 0043 -> 0044` round trip, populated downgrade
refusal, workflow immutability, pinned Case lifecycle, and concurrent channel-
identity convergence.

These tables do not make the deployment universal or active. All code-owned
packs remain `runtime_ready=false`; live webhook adoption, provider-message
deduplication by channel identity, and legacy recruitment separation are later
Release B work.

## Redis

Redis serves multiple roles — all ephemeral (not backed up):

| Role | Usage | Key pattern |
|---|---|---|
| **RQ broker** | Job queue for 5 queues (webhook_high, recovery, persistence_low, ingest, followup) | `rq:queue:*` |
| **Cache** | General-purpose cache (preamble cache, etc.) | `cache:*` |
| **Pub/sub** | Socket.IO cross-process emit bridge (`AsyncRedisManager`) | `socketio:*` |
| **Semantic cache** | LLM response cache for non-personalized knowledge queries | `semcache:*` |
| **Presence** | Recruiter presence (who's online, viewing what) | `presence:*` |
| **LLM semaphore** | Cross-process concurrency limit for LLM/embedding calls | `llm_sem:*` |
| **Rate limiting** | Auth endpoint rate limit counters | `ratelimit:*` |
| **Token usage** | LLM token + cost accounting | `usage:*` |

### Redis safety rules
- **Redis is not backed up.** Never store critical state in Redis — if data must survive a Redis flush, it belongs in Postgres.
- **No password in local dev.** Production config in [`deployment-guide.md`](../ops/deployment-guide.md).
- Redis isolation in tests via `conftest.py:_isolate_redis` auto-use fixture (monkeypatches to no-op double).

## Backup & Restore

- **Production backup:** `make backup` — `pg_dump` from prod Postgres → OneDrive (timestamped `.sql.gz`).
- **Restore to local dev:** `make restore` — restores latest OneDrive backup into local dev DB.
- **Full droplet backup:** `make backup-full` — env + DB + KB uploads + Caddy TLS → `backups/<ts>.zip`.
- **Restore to fresh droplet:** `make restore-prod BUNDLE=<path>`.

See [`droplet-backup-restore.md`](../ops/droplet-backup-restore.md) for the full runbook.
