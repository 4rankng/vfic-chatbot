# legacy/supabase-pre-rewrite — DECOMMISSIONED

**Status:** DEAD / history-only. Do not run, do not treat as a live schema.

This directory is the Supabase data layer from **before the 2026-06-26
big-bang cutover** that replaced n8n + Supabase with the self-hosted
FastAPI + LangGraph + Postgres/pgvector + Redis stack.

## What replaced it

- **Live DDL:** `backend/alembic/versions/` (`0001_baseline.py` + successors).
  The live tables are `users`, `conversations`, `messages`, `outbound_messages`,
  `leads`, `lead_events`, `follow_up_tasks`, `bot_runs`, `jobs`, `companies`,
  `projects`, `knowledge_documents`, `knowledge_chunks`, `audit_events`
  (plus `memories`, `message_dedup`, `system_settings`).
- **Authorization:** app-level JWT (`backend/app/api/dependencies.py`), not
  Supabase RLS / `is_vfic_staff()` / `is_vfic_admin()`.

## Why it differs from the live schema

This snapshot describes the *old* shape: `profiles` (FK to `auth.users`),
`vfic_chat_histories`, `documents`, `memories` (old form), `bridge_event_log`,
RLS policies, and Supabase Auth functions. None of these run anywhere. The
table/enum names here intentionally diverge from the live alembic schema —
that divergence is the record of the rewrite, not drift to "fix".

## Contents

- `schema.sql` — consolidated point-in-time snapshot (old catalog)
- `migrations/*.sql` — the ordered old change log
- `functions/vfic_create_user/` — old Supabase edge function (replaced by
  `backend/app/api/auth.py`)
- `seed_vfic_minicrm_admin.sql` — old Supabase-Auth seed (replaced by
  `backend/scripts/create_admin.py`)
