# CLAUDE.md — VFIC ATS (ChatBotN8N)

This repo runs the VFIC recruitment stack: a **FastAPI + LangGraph** chatbot
backend (`backend/`), a **self-hosted Postgres+pgvector + Redis** data layer,
and a **React / react-admin** console (`frontend/`, brand *Ting Ting* /
*VFIC miniCRM*). The whole stack is deployed as Docker images to a single
droplet (`bot.tingting.vip`) behind Caddy; **the repo is the source of truth**
— the live service is rebuilt from it alone.

> **History:** until 2026-06-26 the brain was **n8n** and the data layer was
> **Supabase**. Both were decommissioned in a big-bang cutover. They are now
> **legacy / disaster-recovery only** (see `legacy/`).
> Any instruction elsewhere that treats n8n or Supabase as live is stale.

## ⚑ The repo IS the source of truth (disaster-recovery rule)

The live system runs Docker images **built from this repo** — there are no
in-place cloud edits to mirror anymore. So the rule is simple: **every change
must be committed**, and the repo must always contain enough to rebuild the
service (`alembic/` for schema, `backend/` + `frontend/` for code,
`docker-compose.yml` + `Caddyfile` for topology).

| Change you make | What MUST be committed alongside it |
|---|---|
| **DB schema** — table/column/index/enum/function/trigger | a new `backend/alembic/versions/<NNNN>_<name>.py` migration (the live DDL is `alembic/versions/0001_baseline.py` + successors) |
| **Backend code** (`backend/app/**`) | the change itself; it ships on the next `franknguyenvd/vfic-backend` image rebuild + `make deploy` |
| **Frontend code** (`frontend/**`) | the change itself; it ships on the next `franknguyenvd/vfic-frontend` image rebuild + `make deploy` |
| **Infra topology** | `backend/docker-compose.yml`, `backend/Caddyfile`, root + `backend/Makefile` |

Do not consider a task done until the change is committed. The `supabase/`
tree is **not** live — do not "sync" to it.

## Infrastructure references (live)

- **Backend**: FastAPI app `app.main:app` (10 routers under `/api/v1` +
  `/realtime` SSE + `/webhooks/zalo`). Entry point `backend/app/main.py`.
  The "graph" (`app/graph/runner.py`) is a hand-rolled state machine, not the
  LangGraph library. LLMs: MiniMax (agent + safety) + Gemini (embeddings,
  `vector(3072)`).
- **External integrations (gotchas — do not re-break these)**:
  - **Zalo is the Bot Platform** (`bot-api.zaloplatforms.com`), NOT the
    Official Account. Inbound verifies `X-Bot-Api-Secret-Token` (NOT the OA
    `X-Zevent-Signature` HMAC); outbound sends via `ZaloBotSender`
    `/bot{token}/sendMessage`. Single client: `app/services/zalo_bot_service.py`;
    secrets `ZALO_BOT_TOKEN` + `ZALO_BOT_WEBHOOK_SECRET`. (The OA client
    `app/services/zalo_service.py` was deleted 2026-06-27.)
  - **MiniMax uses the international endpoint**:
    `MINIMAX_BASE_URL=https://api.minimax.io/v1`. The key is an international
    key; the domestic `api.minimaxi.com` 401-rejects it (code 2049). Do not
    revert to the domestic URL.
- **Data layer**: self-hosted **Postgres 16 + pgvector** + **Redis 7**, both
  containers in `backend/docker-compose.yml`. Schema = `backend/alembic/`.
  No DB-level RLS — authorization is enforced in the app
  (`app/api/dependencies.py`).
- **Workers**: RQ — `worker-chatbot` (queues `webhook_high`, `persistence_low`),
  `worker-ingest` (`ingest`), `scheduler` (`rqscheduler`). Chat-turn concurrency
  is guarded by `conversations.bot_locked_until` + an optimistic `version`
  field — do not remove either.
- **Edge**: Caddy (auto-TLS) → `web` (FastAPI) + `frontend` (nginx SPA).
- **Droplet**: `bot.tingting.vip` (1 vCPU / 2 GB). Prod dir `/opt/vfic`.
- **Images**: `franknguyenvd/vfic-{backend,frontend}` on DockerHub.
- **Deploy**: root `Makefile` → `make deploy` builds+pushes both images and
  rolls the droplet. Dev: `make dev` (Postgres+Redis+Adminer in docker,
  backend + frontend on the host with hot-reload).

## Legacy / DR-only (do not treat as live)

- **`legacy/supabase-pre-rewrite/`** — the decommissioned Supabase schema
  (`schema.sql`, migrations, edge function, seed). Project ref was
  `vichwmxeptglqmzefsiq`. Kept for history only; the live DDL is alembic.
- **`n8n-workflows/`** — exported n8n workflow JSON (5 workflows). Removed in
  the post-cutover cleanup; n8n is fully severed. The ported prompts now live
  as the canonical source in `backend/app/graph/lead_memory_prompts.py`.

## Repo layout

```
backend/          FastAPI + LangGraph backend (api / services / models / graph / workers)
                  alembic/ = live DDL (0001_baseline.py + successors); Dockerfile + compose
frontend/         React + react-admin console (Atomic-CRM-derived, vi-only). See frontend/CLAUDE.md.
legacy/           decommissioned Supabase layer (DR/history only)
kb/               knowledge-base source docs (LGDisplay bus timetable, guidelines)
.omc/             OMC state, runbooks, plans, specs (gitignored operational artifacts)
```

## Conventions

- **Language**: code/identifiers/comments/commits in **English**; user-facing
  strings in the console are **Vietnamese** (the app is vi-only — see
  `frontend/CLAUDE.md`).
- **Naming**: snake_case for SQL / DB identifiers (never hyphens).
- **Frontend specifics** (Tailwind v4, shadcn, ra-core, dev commands):
  see `frontend/CLAUDE.md` and `frontend/AGENTS.md`.
