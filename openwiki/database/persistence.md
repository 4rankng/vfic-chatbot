---
type: system
title: Database overview — Alembic-owned schema and pgvector retrieval
description: How the schema is owned (hand-written Alembic migrations, SQLAlchemy 2.x models mirror it), the canonical migration heads, the key tables (users, conversations, messages, leads, knowledge chunks, integration_settings, external_source_sync_state, bot_runs), and the dev seeding workflow.
tags: [database, alembic, sqlalchemy, pgvector, postgres, migrations, models]
verified:
  - by: openwiki/0.5.0
    at: 2026-09-21T02:42:43.794Z
sources:
  - id: openwiki-source-01644bcf15ad03dc09c5d263
    resource: repo://backend/alembic/versions/0047_canonical_channel_identity.py
  - id: openwiki-source-fd1d50d2a6f6710b3af3e2a7
    resource: repo://backend/app/core/vector.py
  - id: openwiki-source-a89af3f6f98ea26a1605ee61
    resource: repo://backend/app/graph/grounding.py
  - id: openwiki-source-8f27a28439eaf3ce0c8244eb
    resource: repo://backend/app/services/retrieval/repository.py
  - id: openwiki-source-d90fca79839a07479341ddb0
    resource: repo://backend/Makefile
  - id: openwiki-source-fa1d9591fcc1f4e1672f652e
    resource: repo://backend/scripts/bg_deploy.sh
  - id: openwiki-source-012f2c78e3b1446dfc35803f
    resource: repo://Makefile
generated: { by: "opencode", at: "2026-09-21T02:42:43.794Z" }
---

PostgreSQL + pgvector hold the durable state for TingHire. The schema is
owned by hand-written Alembic migrations; the SQLAlchemy 2.x models
mirror those tables and never generate migrations themselves. This split
keeps schema changes reviewable as plain DDL and lets the app evolve
without the ORM guessing.

## Schema ownership

- **Hand-written DDL** lives under `backend/alembic/versions/`. Each
  migration is a small `.py` file with explicit `upgrade()` /
  `downgrade()` and is reviewed the same way as any other code change.
  There is no autogenerate in the deploy path.
- **SQLAlchemy 2.x models** mirror the schema in `backend/app/models/`.
  A model change without a matching migration file is rejected by the
  release gate (`make release-check`) which fails if Alembic reports
  more than one head or a drift.
- **Canonical heads** are pinned in the README; the deploy script
  (`backend/scripts/bg_deploy.sh`) widens the alembic version column
  and runs `alembic upgrade head` against the new image BEFORE bringing
  up the inactive web color.

## Models inventory

`backend/app/models/` holds one file per bounded concept:

| File | Concept |
|---|---|
| `user.py` | `User` (admin / recruiter), `UserTokenVersion` (bumps on disable/delete) |
| `audit.py` | `AuditEvent` (append-only audit rows for privileged actions) |
| `password_reset.py` | One-shot OTPs for `/auth/forgot-password` / `/reset-password` |
| `conversation.py` | `Conversation`, `ConversationProjectState`, `BotRun`, `BotRunOutcome` |
| `message.py` (in `conversation.py`) | Inbound + outbound message rows |
| `lead.py` | `Lead` + stage transitions (Mới / Đang liên hệ / Đã đăng ký / Bỏ qua) |
| `contact.py` | `Contact`, `ContactChannelIdentity` |
| `job.py` | Job listings surfaced by the bot |
| `persona.py` | Agent persona bodies |
| `company.py` | `Project` (the recruitment domain's per-factory scope) + aliases |
| `knowledge.py` | `KnowledgeBase`, `KnowledgeBaseDirectFile`, chunks with `pgvector` embeddings |
| `ingestion_template.py` | Templates that drive knowledge ingest |
| `integration.py` | `IntegrationSetting` (DB-first, AES-GCM encrypted) |
| `channel_account.py` | `ChannelAccount`, partial-unique `uq_channel_accounts_one_active_facebook_messenger` for single-active Facebook Page |
| `installation.py` | `InstallationManifest`, `InstallationManifestRevision`, persona-version linkage |
| `worker_feature.py` | Worker feature flags |
| `outbox.py` | `Outbox` (transactional outbox for channel sends) |
| `bus.py` | Bus timetables (legacy surface, kept read-only) |
| `case.py`, `case_workflow.py` | Recruitment case workflow |
| `external_source_sync_state.py` | External KB sync state |
| `single_page_external_source_sync_state.py` | Per-Page external sync state |
| `provenance.py` | Embedding provenance |
| `base.py` | Shared SQLAlchemy `Base` + naming conventions |

## Embeddings and pgvector

Knowledge chunks live in `KnowledgeBase → KnowledgeChunk` with the
embedding column declared via `pgvector`. The helper
`backend/app/core/vector.py` builds vector literals (`vec_literal`)
the SQLAlchemy queries need; the retrieval layer (`backend/app/services/
retrieval/`) ranks by cosine similarity + lexical overlap and re-ranks
in the graph layer (`backend/app/graph/grounding.py`).

`embedding_dim` is sourced from settings (`Settings.openrouter_embedding_dim`,
default from `OPENROUTER_EMBEDDING_MODEL`) and validated on every insert.
Resizing the embedding dim requires a full re-embed, scheduled through
`worker-ingest`.

## Migration conventions

- Every migration is **additive** when possible (blue/green safe).
  Non-additive migrations use `make deploy-breaking`, which drains both
  web colors, applies the change, and brings the new color up on the
  new schema — accepting brief downtime for operator intent.
- Multi-head migrations are forbidden: the release check
  (`alembic heads | wc -l == 1`) is a binary gate.
- `scripts.widen_alembic_version` runs before `alembic upgrade head` so
  the alembic version column accommodates the future migration count
  without an extra round-trip.
- `migration 0047` introduced the partial unique index
  `uq_channel_accounts_one_active_facebook_messenger` enforcing
  single-active at the DB level (the app layer enforces it in code).

## Dev seeding

`make db` (root Makefile / `backend/Makefile`) brings up Postgres + pgvector
+ Redis + Adminer in docker, runs the alembic baseline, and creates a
default admin (`admin@vfic.dev` / `admin123`) via
`backend/scripts/create_admin.py`. The seed-data script
(`backend/scripts/seed_dev.py`) populates a realistic dev dataset.

`make restore` (root Makefile) overwrites the local DB from a backup,
stamps alembic at head, and resets every user's password to `admin123`
so a fresh checkout can run the full app without re-onboarding.

## What never lives in PostgreSQL

- Decrypted secrets — they flow from `IntegrationSettingsService` to
  the runtime configs and never appear as plaintext rows.
- Bot-turn content — `DecisionTraceBuilder` accepts only allowlisted
  control-flow events (see [openwiki/bot/decision-trace.md](../bot/decision-trace.md)).
- Webhook bodies — the audit row records the action and changed keys;
  the body itself never enters the database.
- LLM client bundles — cached process-local in `_client_cache` with a
  bounded retirement window (see [openwiki/access/integrations-credentials.md](../access/integrations-credentials.md)).

These are explicit invariants enforced by the surrounding layers, not by
the schema.
