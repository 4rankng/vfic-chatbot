# OpenWiki brief — TingHire

This brief steers OpenWiki when documenting TingHire. It is owned by the team;
OpenWiki reads it but never rewrites it during normal runs.

## What TingHire is

TingHire (formerly Ting Ting / VFIC miniCRM) is a Vietnamese recruiting
chatbot + recruiter console built on Zalo. Candidates chat with an LLM agent
about job openings; recruiters take over conversations, manage the job board,
and monitor the bot from a web console. Production runs on a single
DigitalOcean 2 vCPU / 4 GB droplet (`bot.tingting.vip`) — the hard constraint
that shapes every capacity decision.

The repo is a two-package project, not a monorepo:

- `backend/` — Python 3.12 / FastAPI, async-first. SQLAlchemy 2.x async over
  PostgreSQL 16 + pgvector; Redis (broker, cache, presence, Socket.IO fan-out);
  RQ job queue strictly off the synchronous answer path; JWT auth (PyJWT) +
  passlib[argon2]; bot turns run through a LangGraph-style manual pipeline in
  `backend/app/graph/` with LLM calls funneled through `backend/app/graph/clients.py`.
- `frontend/` — React 19 + ra-core 5 (react-admin headless) + Vite +
  TypeScript strict; TailwindCSS v4 + shadcn/ui; TanStack Query v5; Socket.IO
  client. Vietnamese-first UI copy.

There is no `shared/` package; cross-cutting types live per package.

## Roles

| Role | Vietnamese | Scope |
|------|-----------|-------|
| admin | Quản trị | Full access |
| recruiter | Tuyển dụng | Recruiter console: conversations, job board, KB |

Candidates are leads (`leads` table), not users — they authenticate by Zalo
user ID, never by password.

## Where to look first

- `AGENTS.md` (root) — the always-loaded agent constitution; `TECH.md` —
  system map and stack.
- `docs/codebase-summary.md` — repository map.
- `docs/system-architecture.md` — architecture, request lifecycle, queue model.
- `docs/code-standards.md` — code conventions (`standards/coding-style.md`
  holds project-specific preferences and points there).
- `docs/testing.md` — testing approach.
- `docs/deployment-guide.md` — production stack, deploy, backup/restore.
- `standards/agent-completion-checklist.md` — completion record template.

## Key boundaries to preserve

- API transport lives in `backend/app/api/`; business logic lives in
  `backend/app/services/`. Do not collapse them in the docs.
- Bot-turn behavior lives in `backend/app/graph/` and depends on Protocols
  from `graph/ports.py`; concrete dependencies are wired in `factories.py`.
- Models mirror the hand-written Alembic schema (`backend/alembic/versions/`);
  ORM models do not generate migrations.
- Frontend dependency direction is `atomic-crm` → `admin` → `ui`; product code
  lives in `frontend/src/components/atomic-crm/`.
- Keep I/O async; avoid raw SQL and circular imports; offload blocking crypto.
- LLM calls go through `backend/app/graph/clients.py`.
- Structured logging only — never log secrets, PII, or message content.

## Conventions

- Python ≥ 3.12, Ruff (line 100), pytest with `asyncio_mode = "auto"`.
- TypeScript strict (`noUnusedLocals`/`noUnusedParameters`), no `any` in
  `admin/`, `hooks/`, `lib/` (ESLint error).
- REST API under `/api/v1`; asyncpg for the app, sync psycopg for Alembic/RQ.
- Vietnamese-first UI copy; the answer language follows the candidate.
- pydantic-settings refuses prod boot on default `JWT_SECRET` or `*` CORS.

## What to emphasize in pages

- System responsibility and ownership, not just symbol inventories.
- Runtime/build entrypoints (`backend/app/main.py`, `frontend/src/main.tsx`).
- Mechanisms and control/data flow across the API → services → graph → data
  layering.
- The bot turn: routing (TypeSafe Jev fan-out), grounding, pre-send ownership
  guard, deadline-aware execution, LLM semaphore throttling.
- Retrieval: hybrid PG full-text + pgvector ANN, RRF merge, section-based
  chunking, semantic response cache, prompt-prefix caching, honesty policy.
- Upstream/downstream relationships (Zalo OA, OpenRouter/Gemini/MiniMax, PG,
  Redis, Resend).
- Invariants and failure behavior (safety filter, suppression on recruiter
  takeover, grounded refusal when data is missing).
- Configuration, security, and operational consequences on the 2 vCPU box.

## What to omit

- Pages that only mirror a directory or list symbols without explaining a
  system.
- Pages that repeat `docs/codebase-summary.md` verbatim — cross-link instead.
- Speculative behavior not present in the current source.
- Lockfiles, generated bundles, and any path matched by `.openwikiignore`.

## Language

Generate factual pages in English. Keep Vietnamese domain terms (tuyển dụng,
ứng viên, anh/chị, etc.) in italics on first use and use them consistently
across pages.
