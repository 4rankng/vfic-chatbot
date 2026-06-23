# CLAUDE.md — VFIC ATS (ChatBotN8N)

This repo runs the VFIC recruitment stack: an **n8n** chatbot brain, a
**Supabase** (Postgres) data layer, a **React/Atomic-CRM** console
(`frontend/`), and a trimmed **Chatwoot** fork. Each layer has a live
cloud instance that is edited in place; the repo must stay a faithful
mirror so the service can be rebuilt from it alone.

## ⚑ Sync live → local after EVERY infra change  (disaster-recovery rule)

**Why:** if a cloud account is lost (Supabase, n8n), the repo must contain
enough to rebuild the service. Live edits made via MCP are *not* automatically
reflected in the repo — so mirror them immediately.

| Change you made live | Local file(s) you MUST also update |
|---|---|
| **Supabase schema** — migration, column, RLS policy, function, trigger, index, enum | (a) append the SQL to `supabase/migrations/<YYYYMMDD>_<name>.sql`; (b) **regenerate `supabase/schema.sql`** snapshot from the live catalog (see below) |
| **Supabase edge function** | mirror under `supabase/functions/<name>/` |
| **n8n workflow** edit (via n8n-mcp) | re-export the workflow JSON to `n8n-workflows/<Workflow Name>.json` |
| **Chatwoot** brand/code change | follow `Makefile` (`brand-apply`/`build`/`deploy`); the forked sources live in `chatwoot/` |

Do not consider a live infra task done until the local mirror is updated and
committed. `git status` should show the matching local change alongside any
code change.

### Regenerating `supabase/schema.sql`

`pg_dump` / the Supabase CLI are not assumed available; regenerate from the live
catalog with `mcp__supabase__execute_sql` against project
`vichwmxeptglqmzefsiq`. Run these in parallel, then assemble DDL in order
(extensions → enums → tables → FKs → indexes → functions → triggers → RLS):

- columns/types/defaults/nullability:
  `format_type(atttypid, atttypmod)` + `pg_get_expr(adbin)` over `pg_attribute`
- constraints: `pg_constraint` + `pg_get_constraintdef(oid)`
- indexes: `pg_indexes.indexdef` (skip PK/UNIQUE-constraint-backed names)
- functions: `pg_get_functiondef` for `prokind='f'` in `public` **excluding the
  pgvector C helpers** (filter by business names: `is_vfic_*`, `touch_updated_at`,
  `vfic_*`)
- triggers: `pg_get_triggerdef` over `pg_trigger` (non-internal, public)
- RLS: `pg_class.relrowsecurity`; policies from `pg_policies`

`migrations/` remains the ordered change log; `schema.sql` is the consolidated
point-in-time snapshot regenerated after each change.

## Infrastructure references

- **Supabase**: project `VFIC-Chatbot`, ref **`vichwmxeptglqmzefsiq`**
  (region ap-northeast-2, Postgres 17). Use `mcp__supabase__*`. Embeddings are
  `vector(3072)`. The CRM `users` resource aliases to the live `profiles` table.
- **n8n**: edit workflows **in place** (never create new ones). Known workflows:
  `VFIC Chatbot` (`iodmXzjRe03KqPdB`), `VFIC Knowledge Ingest`
  (`wY4YI1nFu1bw0ERt`), `VFIC Chatwoot Bridge`, `VFIC Persist Lead`,
  `VFIC Persist Memories`. Local copies: `n8n-workflows/`. The n8n MCP token is
  a JWT that **401s against the native REST `/api/v1`** — export via MCP tools,
  not curl.
- **Chatwoot**: live at `chat.tingting.vip`; deploy via `make deploy`
  (brand → build amd64 → ship → restart). Brand is DB-driven
  (`installation_configs`), not YAML. Never `docker compose down -v`
  (wipes Redis → lockout).
- **Droplet**: `bot.tingting.vip` (1 vCPU / 2 GB) hosts n8n + Chatwoot containers.

## Repo layout

```
frontend/         React + react-admin console (Atomic CRM). See frontend/CLAUDE.md.
supabase/         LIVE VFIC schema: schema.sql (snapshot), migrations/ (change log),
                  functions/, seed_vfic_minicrm_admin.sql
n8n-workflows/    exported n8n workflow JSON (5 workflows)
chatwoot/         trimmed/rebranded Chatwoot fork
chatwoot Makefile brand/build/deploy automation for chat.tingting.vip
.omc/             OMC state, runbooks, plans, specs
```

## Conventions

- **Language**: code/identifiers/comments/commits in **English**; user-facing
  strings in the console are **Vietnamese** (the app is vi-only — see
  `frontend/CLAUDE.md`).
- **Naming**: snake_case for SQL / DB / n8n identifiers (never hyphens).
- **Frontend specifics** (Tailwind v4, shadcn, ra-core, dev commands):
  see `frontend/CLAUDE.md` and `frontend/AGENTS.md`.
