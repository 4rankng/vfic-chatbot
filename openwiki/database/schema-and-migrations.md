---
type: data
title: Schema, hand-written Alembic migrations, and seed data
description: How the schema is owned (Alembic writes DDL, SQLAlchemy 2.x models mirror it), the canonical migration heads, the key tables (users, conversations, messages, leads, knowledge chunks, integration_settings, external_source_sync_state, bot_runs), and the dev seeding workflow.
tags: [alembic, sqlmodel, migrations, pgvector, seed, schema, encryption]
verified:
  - by: openwiki/0.5.0
    at: 2026-09-08T09:17:45.993Z
---

Schema ownership is **explicit**: Alembic writes the DDL; SQLAlchemy 2.x
ORM models mirror the resulting tables for queries. The models never
autogenerate migrations, and the baseline migration (0001) is a hand-
written `op.create_*` set that replaced the Supabase schema at the
big-bang cutover. This split lets the model layer evolve without
quietly rewriting the database, and lets the migration layer carry
operational metadata (encrypted columns, partial unique indexes,
triggers) that does not belong in declarative models.

## Directory layout

```
backend/alembic/
├── env.py                  # Async + sync engine config; runs against Postgres 16
├── script.py.mako          # Standard Alembic template
└── versions/
    ├── 0001_baseline.py    # Greenfield schema (replaces Supabase)
    ├── 0002_user_token_version.py
    ├── ...
    ├── 0051_bot_run_decision_trace.py
    ├── 0052_external_source_sync_state.py
    ├── 0053_single_page_external_source_sync_state.py
    └── 091e7edc9f76_merge_0013_password_reset_otps_0013_.py
```

The latest head on the main branch is `0053_single_page_external_source_sync_state`.
There is one merge migration (`091e7edc9f76`) that resolved a parallel
heads situation during the password-reset OTP work. `make release-check`
asserts exactly one Alembic head before any deploy.

## Baseline (0001) — the source-of-truth cutover

`0001_baseline.py` is the cutover schema that replaced Supabase:

- Self-hosted **PostgreSQL 16 + pgvector**.
- Clean tables with real FKs, typed messages with `created_at`,
  `BOT` / `HUMAN` / `CLOSED` modes, **HNSW vector indexes**.
- Own users + JWT (no RLS, no Supabase Auth).
- The bus-timetable knowledge graph + SQL functions and the
  `match_memories` / `match_documents` RAG functions are ported
  VERBATIM from the live Supabase catalog so chatbot behavior is
  identical.
- A `documents` VIEW shims the old `documents` table over
  `knowledge_documents` / `knowledge_chunks` so the verbatim bus-rebuild
  function works unmodified.

The baseline `docstring` is explicit about why this directory is **not**
mirrored to `../supabase/migrations`: at the cutover Supabase is
decommissioned, not migrated in place. Mirroring would pollute the
legacy live-Supabase change log with a schema for a different database.
`backend/alembic` is the canonical source of truth.

## Key tables

The schema covers the full product surface; the central tables are:

| Table | Owns | Notes |
|---|---|---|
| `users` | Login + RBAC | argon2 hash, `role` (`admin` / `recruiter`), `disabled`, `ver` (token-version, bumped on disable/delete so rotated JWTs cannot outlive the user) |
| `password_reset_otps` | OTP-based password reset | Resend-backed delivery |
| `companies`, `projects` | Tenant + project hierarchy | Project-owned knowledge modes (migration 0048) |
| `personas` | Persona body + terminology | Activation + per-adapter assignment (migration 0049) |
| `knowledge_bases`, `knowledge_documents`, `knowledge_chunks` | RAG corpus | `embedding vector(3072)` + halfvec HNSW (migration 0014); versioned via `kb_versions` (0023) |
| `jobs` | Job postings | Search / sort |
| `conversations`, `messages` | Conversation lifecycle | DB lock + owner token; FK to `bot_runs` cascade-delete |
| `bot_runs` | Per-turn audit row | `decision_trace` JSONB (0051), `stage_timings`, runtime stamp (0045), trace_id (indexed), outcome metadata |
| `leads`, `lead_events`, `follow_up_tasks` | Lead kanban | Stages, score, follow-up cadence |
| `integration_settings` | Encrypted credentials | AES-GCM `v1:` (no AAD) + `v2:` per-Page tokens (AAD = page_id) — see [integrations-credentials.md](../access/integrations-credentials.md) |
| `installation_manifest_revisions` | Runtime authority stamp | FK `RESTRICT` from `bot_runs.runtime_revision_id` so authority rows cannot be removed while bot runs reference them |
| `external_source_sync_state`, `single_page_external_source_sync_state` | Sync bookkeeping | Per-link `auto_sync_enabled`; deterministic render and prior-page preservation on failure (0052, 0053) |
| `audit_events` | Append-only audit | `record_audit` flushes; caller commits so audit composes with other writes |
| `outbox` | Outbound durable commands | Reconciliation picks up stale rows via the dispatcher tick |

## pgvector layout

`backend/app/core/vector.py` and `backend/app/core/embedding.py` pin the
embedding dimension:

- `EMBEDDING_DIM = 3072` is a **schema-pinned code constant** (a free
  parameter would break both writes — wrong-width vector column — and
  ANN retrieval). The constant's docstring is explicit: the embedding
  model output dimension must equal this value.
- `knowledge_chunks.embedding` is `vector(3072)` (baseline 0001) and the
  ANN candidate index is `halfvec(3072) HNSW` (migration 0014).
- `memories.embedding` mirrors the same fix in migration 0016
  (`query_perf_indexes`).
- The retrieval layer gates ANN on the dimension and warns on drift
  rather than silently degrading to exact search.

## Migrations as operational state

Several migrations encode operational decisions that are not obvious from
the model:

- `0041_version_scope_typed_authority` — typed authority scopes.
- `0042_installation_revision_lifecycle` — installation manifest
  revisions become immutable once a bot run references them.
- `0045_runtime_authority_stamps` — `bot_runs.runtime_revision_id`,
  `authority_generation`, `runtime_fingerprint` added so a clean cutover
  never lets pre-authority jobs inherit today's capabilities.
- `0047_canonical_channel_identity` — `channel_accounts` with the partial
  unique index `uq_channel_accounts_one_active_facebook_messenger`.
- `0050_data_ingestion_recovery` — recovery semantics for the ingest
  worker.
- `0051_bot_run_decision_trace` — adds `bot_runs.decision_trace` JSONB.
- `0052_external_source_sync_state` and
  `0053_single_page_external_source_sync_state` — Google-Sheet-driven
  sync bookkeeping for direct-context FAQ pages.

The migration files' docstrings carry the rationale (e.g. "innocent-
looking migration X would have silently dropped audit rows"). The
`make release-check` precondition (`alembic heads | wc -l == 1`) keeps
the migration history linear.

## Model layer

`backend/app/models/__init__.py` imports each model so `Base.metadata`
reflects the full schema when Alembic compares. The header comment is
the rule:

> "Schema is owned by Alembic (raw-SQL baseline); these mirror the tables
> for queries."

Models therefore:

- Never run `alembic revision --autogenerate`. New tables / columns go
  through a hand-written migration first, then a model is added.
- Use SQLAlchemy 2.x typed `Mapped[...]` columns.
- Carry short docstrings explaining the operational invariant (e.g.
  `IntegrationSetting` notes AES-GCM + AAD context binding;
  `BotRun.decision_trace` notes the bounded allowlist).

## Seed data

`backend/scripts/seed_dev.py` populates the local dev database with
realistic Vietnamese recruitment data:

- Idempotent: truncates all seed-owned tables, then inserts fresh data.
- Marked **local development only** — `__main__` prints a guard and
  refuses to run against `app_env != "development"`.
- Run via `make seed` from the repo root, or
  `cd backend && python -m scripts.seed_dev`.

`backend/scripts/create_admin.py` bootstraps the first admin / recruiter
user:

- Idempotent: refuses if the email already exists.
- `--only-if-no-admins` skips when ANY admin exists; used as a deploy
  bootstrap guard.
- Uses the **sync** database URL (`psycopg`) — `hash_password_sync` is
  the sync argon2 helper, deliberately split from the async
  `hash_password` so scripts never accidentally block the event loop.

## Why this ownership boundary

- **Models describe the present.** They are the contract for queries and
  tooling.
- **Migrations describe the past.** They encode the operational
  decision, the rollout constraint, and the rollback story.
- **Autogenerate would erase that history.** A `Base.metadata` diff does
  not remember *why* the column was nullable, *why* the index is partial,
  or *why* the migration was sequenced after another. The migration is
  the audit log; the model is the type system.
