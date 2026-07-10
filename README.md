# Ting Ting — VFIC miniCRM (Zalo Recruiting ChatBot)

Ting Ting is the recruiter/admin console for a **Vietnamese recruiting platform**
that sources candidates over **Zalo**. A FastAPI backend hosts a Zalo-facing
chatbot that screens, nudges, and routes candidates, while a Vietnamese-only
React Admin console (the "miniCRM") lets recruiters watch conversations, take
over when needed, manage leads on a kanban board, and curate the knowledge base
the bot reasons over.

> **Brand:** the product is **Ting Ting** / **VFIC miniCRM**. The frontend npm
> package is still internally named `atomic-crm` because it was derived from the
> open-source *Atomic CRM* / *shadcn-admin-kit* template — this is a historical
> footnote only, never the product name.
>
> **Standalone.** This is a self-contained FastAPI service. There is **no
> Chatwoot** and **no Supabase** (Supabase was decommissioned 2026-06-26).

## What it does

- **Inbound Zalo chatbot** (Bot Platform + Official Account) answers candidates
  24/7, runs a multi-step turn pipeline (agent → safety → send), and extracts
  lead info from the conversation.
- **Human inbox** with realtime Socket.IO push: recruiters read live threads,
  take over, run semi-auto, or hand back to the bot.
- **Lead kanban** with stages, tags, follow-ups, and AI-assisted actions.
- **Knowledge base** (RAG) per project: recruiters upload docs, the bot indexes
  them (pgvector + HNSW + exact re-rank) and grounds replies in them.
- **Proactive follow-up** worker nudges cold candidates on a 6h/24h/46h cadence
  with a 48h-Zalo-rule-safe margin and Vietnamese opt-out detection.

## Stack

| Layer | Tech |
|---|---|
| Backend | FastAPI, Python 3.12, async SQLAlchemy 2.x (asyncpg), Pydantic v2, RQ workers, rq-scheduler |
| Bot pipeline | Hand-rolled async "LangGraph-style" node chain in `app/graph/runner.py` |
| LLM | MiniMax M2.7 primary (agent), M2.5 (safety); OpenRouter fallback; OpenRouter embeddings + Gemini fallback |
| Data | PostgreSQL 16 + pgvector, Redis 7 (RQ broker + pub/sub + LLM semaphore) |
| Realtime | Socket.IO (ASGI-wrapped) — `conv:<id>` rooms |
| Frontend | React 19.1, react-admin 5.14, Vite 7, TypeScript 5.8 strict, Tailwind v4 (CSS-first), Zustand, TanStack Query, `virtua`, Socket.IO client |
| Edge | Caddy 2 (auto Let's Encrypt) on DigitalOcean |
| Channel | Zalo only (Bot Platform + Official Account) |

## Architecture in one paragraph

A Zalo webhook hits `/webhooks/zalo/{chatbot,oa}`; the handler verifies the
secret, persists and locks the inbound turn, acks in under a second, then runs
the turn directly on a FastAPI event loop. The per-chat Postgres lock has an
owner token and lease heartbeat; if a web process stops mid-turn, the reconcile
worker recovers it through the `webhook_high` RQ queue. The bot-turn pipeline
(`load_conversation_state → typing → agent → fast_safety_filter →
[llm_safety_check] → combine_for_presend → pre_send_guard → send_message`),
grounding the agent in pgvector RAG and MiniMax M2.7. After the reply is SENT,
a `persistence_low` job extracts lead data. A reconcile worker sweeps every 60s
to recover any turn lost to a worker crash. The recruiter console subscribes
over Socket.IO to see each SENT message land in real time.

See **[docs/system-architecture.md](./docs/system-architecture.md)** for the
full component diagram, queue model, and message-lifecycle sequence.

## Quickstart (local dev)

**Prereqs:** Python 3.12, Node 22, Docker, `make`.

```bash
# 1. Start dev stack (Postgres+pgvector :5432, Redis :6382, Adminer :8082),
#    create backend/.env, run Alembic, and seed a dev admin.
make db                       # from repo root, runs: cd backend && make db

# 2. Run backend + workers + frontend + Zalo mock together (Ctrl-C stops all).
make dev
# -> App :  http://localhost:5173   Login: admin@vfic.dev / admin123
# -> Mock: http://localhost:8788    (outbound Zalo is captured locally, not sent)
# -> DB UI: http://localhost:8082   (server: postgres, db: vfic, vfic/vfic)
```

The dev compose intentionally exposes Redis on **6382** (6379 belongs to a
sibling payroll project). Zalo credentials (`ZALO_BOT_API_BASE`,
`ZALO_BOT_TOKEN`) are exported by `make dev` to point at the local mock — no
real Zalo traffic leaves your machine.

To exercise the real bot, fill the third-party keys in `backend/.env`
(`MINIMAX_API_KEY`, `ZALO_BOT_TOKEN`, etc.) and drop the mock env overrides.

## Common commands

```bash
# --- Backend ---
cd backend
make dev                                       # uvicorn --reload + workers + mock
.venv/bin/python -m alembic upgrade head       # apply migrations
.venv/bin/python -m scripts.create_admin --email admin@vfic.dev --password admin123 --role admin
.venv/bin/python -m scripts.seed_dev           # truncate + re-insert Vietnamese dev data (LOCAL only)

# Tests (pure unit, NO live DB/Redis):
REDIS_URL=redis://localhost:6380/0 APP_ENV=development \
  .venv/bin/python -m pytest -q --tb=short

# --- Frontend ---
cd frontend
npm install
npm run dev                # Vite dev server :5173
npm run typecheck          # tsc --noEmit --project tsconfig.app.json
npm run build              # tsc && vite build
npm run test:unit:app      # Vitest (Chromium via @vitest/browser-playwright)
npm run lint               # ESLint 9 flat config
npx playwright test        # e2e against build:e2e dist on :4173
```

> Note: the local test command pins Redis port **6380** while dev compose
> exposes **6382**. This implies a dedicated test Redis is expected — see
> [docs/project-roadmap.md](./docs/project-roadmap.md) (Known Issues).

## Deploy

Deployment is **manual**, driven from a developer mac over SSH (no CI deploys
to production). The Makefile orchestrates buildx push + remote recreate.

```bash
make deploy            # build+push BOTH images, then full deploy (compose sync, .env gen, migrate, bootstrap admin, up)
make deploy-backend    # fast-track: rebuild backend image, pull+migrate+recreate web/workers/scheduler
make deploy-frontend   # fast-track: rebuild frontend image, pull+recreate frontend only
make adminer           # SSH-tunnel to prod Adminer -> http://localhost:18081
make backup            # pg_dump prod -> OneDrive (timestamped .sql.gz)
make restore           # restore latest prod backup into local dev DB (passwords reset to admin123)
make backup-full       # full droplet bundle -> backups/<ts>.zip (env, DB, KB volumes, Caddy TLS)
make restore-prod BUNDLE=backups/<bundle>   # push a bundle onto a FRESH droplet
```

Production: `bot.tingting.vip` (DigitalOcean, 2 vCPU / ~4 GB RAM). Stack lives
at `/opt/vfic`. See **[docs/deployment-guide.md](./docs/deployment-guide.md)**
for the 10-service compose, Caddy routes, env var reference, and
**[docs/DROPLET-BACKUP-RESTORE.md](./docs/DROPLET-BACKUP-RESTORE.md)** for the
full backup/restore runbook.

## Documentation

| Doc | Purpose |
|---|---|
| [docs/project-overview-pdr.md](./docs/project-overview-pdr.md) | Product overview, personas, functional/non-functional requirements, success metrics |
| [docs/codebase-summary.md](./docs/codebase-summary.md) | Repo layout, LOC breakdown, module map, key files table |
| [docs/code-standards.md](./docs/code-standards.md) | Backend + frontend conventions, testing, commits |
| [docs/system-architecture.md](./docs/system-architecture.md) | Component diagram, request lifecycle, queue model, bot-turn pipeline, auth, realtime, RAG |
| [docs/project-roadmap.md](./docs/project-roadmap.md) | Current state, near-term priorities, known issues / tech debt |
| [docs/deployment-guide.md](./docs/deployment-guide.md) | Production deploy, Caddy routing, env reference, health/metrics, security posture |
| [docs/DROPLET-BACKUP-RESTORE.md](./docs/DROPLET-BACKUP-RESTORE.md) | Full droplet backup & restore runbook (finished) |

## Project layout

```
ChatBot/
├── backend/          FastAPI app + Alembic + RQ workers + scripts + compose
│   ├── app/          api/ core/ graph/ models/ schemas/ services/ workers/ realtime/ prompts/
│   ├── alembic/      migrations (HEAD = 0023_kb_versioned_ingestion)
│   ├── mock_servers/ local Zalo mock
│   └── scripts/      create_admin, seed_dev, prod-env, benchmark_*, backup/restore
├── frontend/         React Admin SPA (atomic-crm vendored kit + VFIC app)
│   └── src/components/atomic-crm/   the VFIC app (conversations, leads, knowledge, ...)
├── docs/             this documentation set
├── scripts/          root-level droplet backup/restore shell scripts
├── Makefile          dev / deploy / backup / restore entrypoints
└── README.md         this file
```

## Conventions

- TypeScript strict mode, no `any`.
- Async-first backend; blocking crypto (argon2, JWT) on worker threads via
  `asyncio.to_thread`.
- **`-strip` is load-bearing** in the bot prompt pipeline — never remove it.
- No raw SQL outside Alembic baseline migrations.
- Vietnamese-only frontend strings; English identifiers/comments.
- Conventional commits, no AI references in commit messages.
- Never commit `.env`, `backups/`, credentials, or DB dumps.

See [docs/code-standards.md](./docs/code-standards.md) for the full list.

## License

Proprietary — VFIC internal.
