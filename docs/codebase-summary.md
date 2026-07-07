# Codebase Summary

**Repo:** `git@github.com:4rankng/ChatBotN8N.git` (branch `main`)
**Last updated:** 2026-07-07

A monorepo with two deployable subprojects (`backend/`, `frontend/`) plus
root-level ops scripts. DockerHub images: `franknguyenvd/vfic-backend:latest`
and `franknguyenvd/vfic-frontend:latest` (also tagged `:<git-sha>`).

## Repository layout

```
ChatBot/
├── backend/              FastAPI + RQ workers + Alembic (~19.6k LOC Python)
│   ├── app/
│   │   ├── api/          Routers + dependencies.py        (15 files, 2,173 LOC)
│   │   ├── core/         config, db, redis, security,
│   │   │                 logging, errors, cache,
│   │   │                 ratelimit, embedding, vector,
│   │   │                 text                              (694 LOC)
│   │   ├── graph/        runner, clients, factories,
│   │   │                 tools, safety, prompts,
│   │   │                 proactive                         (2,145 LOC)
│   │   ├── models/       SQLAlchemy 2.x ORM                (932 LOC)
│   │   ├── schemas/      Pydantic v2                       (1,049 LOC)
│   │   ├── services/     conversation/, lead/, knowledge/,
│   │   │                 dashboard/, personas/, project/,
│   │   │                 retrieval/, proactive/ + flat
│   │   │                 zalo_*, integration_settings, auth (67 files, 11,818 LOC)
│   │   ├── workers/      run_worker, chatbot, persistence,
│   │   │                 ingest, followup, reconcile,
│   │   │                 async_runner, scheduler_utils     (943 LOC)
│   │   ├── realtime/     Socket.IO server + bridge         (264 LOC)
│   │   ├── prompts/
│   │   └── main.py        FastAPI app + lifespan + ASGI wrap
│   ├── alembic/          23 migrations + 1 merge head
│   ├── mock_servers/     zalo_mock.py (local :8788)
│   ├── scripts/          create_admin, seed_dev, prod-env,
│   │                     benchmark_models, benchmark_rag,
│   │                     capture_bus_timetable_golden, loadtest/
│   ├── tests/            28 files, pure unit (no live DB/Redis)
│   ├── docker-compose.yml        10-service prod stack
│   ├── docker-compose.dev.yml    Postgres+Redis+Adminer only
│   ├── Dockerfile        python:3.12-slim, pip install -e .
│   ├── Caddyfile         edge routes for bot.tingting.vip
│   ├── .env.example      committed env template (values blank/dev)
│   └── Makefile          dev / db / push / deploy / adminer
├── frontend/             React Admin SPA (~37.4k LOC TS/TSX)
│   ├── src/
│   │   ├── main.tsx      StrictMode + vite:preloadError guard
│   │   ├── App.tsx       renders <CRM/>
│   │   ├── components/
│   │   │   ├── admin/            vendored shadcn-admin-kit (mutable dep)
│   │   │   ├── ui/               vendored Shadcn primitives (mutable dep)
│   │   │   └── atomic-crm/       THE VFIC app
│   │   │       ├── root/             <CRM> resource registration
│   │   │       ├── conversations/    inbox + ChatThread (virtua) + context panel
│   │   │       ├── leads/            kanban + chatops
│   │   │       ├── dashboard/        RecruitingCommandCenter
│   │   │       ├── knowledge/        KnowledgeIngestPanel + project workspace
│   │   │       ├── personas/         persona CRUD + workspace
│   │   │       ├── projects/         ProjectSidebar / BusTimetable / FaqEditor
│   │   │       ├── integrations/     ZaloIntegrationPage
│   │   │       ├── providers/        dataProvider, authProvider, i18nProvider
│   │   │       ├── layout/           Layout + MobileLayout
│   │   │       ├── login/, settings/, profiles/, misc/, automation/
│   │   │       └── inbox/            10 CSS section files (barrel = inbox.css)
│   │   ├── lib/          utils.ts (cn), toSlug.ts, vietnameseSearch.ts
│   │   ├── lib/vfic/     config.ts, humanReplyService.ts,
│   │   │                 knowledgeService.ts, realtimeSocket.ts
│   │   └── hooks/        use-mobile.ts
│   ├── e2e/              Playwright specs (vfic.spec.ts, visual.spec.ts)
│   ├── Dockerfile        node:22 build → nginx:1.27 serve
│   └── package.json      (name "atomic-crm" — historical, not the product)
├── docs/                 this documentation set + DROPLET-BACKUP-RESTORE.md
├── scripts/              backup-droplet.sh, restore-droplet.sh
├── Makefile              dev / deploy / backup / restore (delegates to backend)
└── README.md
```

## LOC breakdown (approximate)

| Area | LOC |
|---|---|
| Backend `app/services/` | 11,818 |
| Backend `app/api/` | 2,173 |
| Backend `app/graph/` | 2,145 |
| Backend `app/schemas/` | 1,049 |
| Backend `app/models/` | 932 |
| Backend `app/workers/` | 943 |
| Backend `app/core/` | 694 |
| Backend `app/realtime/` | 264 |
| **Backend total** | **~19,600** |
| Frontend `src/` (TS/TSX) | ~37,400 |

## Module map — backend `app/`

| Subdir | Responsibility |
|---|---|
| `api/` | FastAPI routers under `/api/v1` (except `realtime`, `webhooks`). `dependencies.py` holds auth deps. |
| `core/` | Cross-cutting infra: config (Pydantic BaseSettings), async DB engine + session, Redis pool, security (JWT/argon2), structured logging + request_id, error handlers, cache, ratelimit, embedding + vector helpers, text utils. |
| `graph/` | The bot-turn pipeline. `runner.py` is the node chain; `clients.py` LLM client wrappers; `factories.py` dependency injection; `tools.py` tool dispatch; `safety.py` fast + LLM safety; `prompts.py`; `proactive/`. |
| `models/` | SQLAlchemy 2.x ORM mirroring the schema. **Does not generate migrations** — Alembic baseline is raw SQL `op.execute`. |
| `schemas/` | Pydantic v2 request/response models. |
| `services/` | Business logic, the largest subpackage. Subpackages: `conversation/`, `lead/`, `knowledge/`, `dashboard/`, `personas/`, `project/`, `retrieval/`, `proactive/`. Flat modules: `zalo_sender`, `zalo_bot_service`, `zalo_oa_service`, `integration_settings`, `auth`. |
| `workers/` | RQ worker entrypoints + async bridge. `run_worker.py` is the container entrypoint. |
| `realtime/` | Socket.IO ASGI server + cross-process emit bridge so workers can push to clients. |
| `prompts/` | Prompt assets. |

## Module map — frontend `src/`

| Subdir | Responsibility |
|---|---|
| `components/admin/` | **Vendored mutable dependency.** shadcn-admin-kit: `admin.tsx`, `data-table.tsx`, `filter-form.tsx`, `simple-form-iterator.tsx`, `file-input.tsx`. |
| `components/ui/` | **Vendored mutable dependency.** Shadcn UI + Radix primitives. |
| `components/atomic-crm/` | **The VFIC app.** All product code lives here. |
| `components/atomic-crm/root/` | `<CRM>` — resource registration, CustomRoutes, providers, theme props. |
| `components/atomic-crm/providers/` | `dataProvider.ts` (react-admin verb mapping), `rest/api.ts` (HTTP client + JWT + 401 refresh), `authProvider.ts`, `i18nProvider.ts` (Vietnamese-only). |
| `components/atomic-crm/conversations/` | Inbox: ConversationList, ChatThread (virtua VList), ConversationContextPanel, WorkspaceShell + WorkspaceIconRail, chatRepository, useConversationRealtime, Zustand `messageStore.ts`. CSS barrel `inbox.css`. |
| `components/atomic-crm/leads/` | Kanban board, lead show/edit, chatops actions. |
| `components/atomic-crm/dashboard/` | RecruitingCommandCenter (Vietnamese metric cards). |
| `components/atomic-crm/knowledge/` | KnowledgeIngestPanel (largest file, 763 LOC) + project workspace shell. |
| `components/atomic-crm/projects/` | ProjectSidebar, ProjectWorkspaceShell, ProjectBusTimetable, ProjectFaqEditor, ProjectFeatures, ProjectPersonaPanel. |
| `components/atomic-crm/personas/` | Persona CRUD + PersonaWorkspaceShell + personaMarkdown. |
| `components/atomic-crm/integrations/` | ZaloIntegrationPage (admin only). |
| `lib/vfic/` | `config.ts` (API base resolution), `realtimeSocket.ts` (Socket.IO singleton), `humanReplyService.ts`, `knowledgeService.ts`. |
| `lib/` | `utils.ts` (`cn()` = clsx + tailwind-merge), `toSlug.ts`, `vietnameseSearch.ts` (diacritic-insensitive). |

## Key files table

| File | Purpose |
|---|---|
| `backend/app/main.py` | `FastAPI(title="VFIC API", version="0.1.0", lifespan=lifespan)`. Registers domain exception handlers, CORS (credentials=True, no `*`), request_id middleware, Socket.IO ASGI wrap, rq-scheduler ticks. |
| `backend/app/core/config.py` | `Settings(BaseSettings)` + `get_settings()` lru_cache singleton. Boot-time safety checks. `active_llm_provider` / `llm_fallback_enabled` properties. |
| `backend/app/core/security.py` | passlib argon2, python-jose HS256 JWT, `asyncio.to_thread` for crypto. |
| `backend/app/core/db.py` | `create_async_engine(..., pool_pre_ping=True)`, `async_session` (`expire_on_commit=False`), `get_db()` (rolls back on exception). |
| `backend/app/graph/runner.py` | Bot-turn pipeline node chain (`run_turn`). Topology documented in module docstring lines 1-18. |
| `backend/app/graph/types.py` | `BotRunState` (line 21), `GraphDeps` (line 32). |
| `backend/app/graph/factories.py` | `build_deps(db)` (line 65) — resolves admin-managed MiniMax/OpenRouter/Zalo creds. |
| `backend/app/graph/clients.py` | MiniMax / OpenRouter LLM clients; `FallbackLLM` (line 343); `_chat_for_role` (line 444); `_llm_call_with_retry` (line 102, 429 handling); `GeminiEmbedder` (line 127). |
| `backend/app/graph/tools.py` | `TOOL_SCHEMAS` + `_dispatch_tool`. Tools: `search_knowledge`, `search_user_memory`, `search_bus_timetable`. |
| `backend/app/graph/safety.py` | `fast_safety_filter`, `parse_verdict`, `build_retry_prompt`, `retry_exhausted_fallback`. |
| `backend/app/graph/llm_semaphore.py` | Redis-backed cross-process LLM concurrency semaphore; `LLMThrottled`. |
| `backend/app/services/zalo_sender.py` | `ZaloChannelSender` facade (line 19) — dispatches per `conv.zalo_channel`. |
| `backend/app/services/zalo_bot_service.py` | `ZaloBotSender` (line 241); `send_message` (line 253); `send_chat_action` (line 335). Base `https://bot-api.zaloplatforms.com`. |
| `backend/app/services/zalo_oa_service.py` | `ZaloOASender` (line 12); `POST /v3.0/oa/message/cs` (line 81). Base `https://openapi.zalo.me`. |
| `backend/app/services/retrieval/repository.py` | pgvector halfvec HNSW + exact re-rank retrieval (line 160). |
| `backend/app/workers/run_worker.py` | RQ worker container entrypoint; calls `Worker.clean_registries()` on startup. |
| `backend/app/workers/chatbot.py` | Chat turn worker (consumes `webhook_high`, `persistence_low`). |
| `backend/app/workers/reconcile.py` | Reconcile sweep (line 43); SETNX non-reentrancy guard; 7 Redis observability counters. |
| `backend/app/workers/followup.py` | Proactive follow-up fan-out (line 74). |
| `backend/app/workers/async_runner.py` | One persistent event loop per worker process (sync RQ → async bridge). |
| `backend/app/realtime/` | Socket.IO server + cross-process emit bridge (264 LOC). |
| `backend/app/api/webhooks.py` | `POST /webhooks/zalo/chatbot` (line 34), `POST /webhooks/zalo/oa` (line 71), `_verify_oa_signature` (line 115). |
| `backend/app/api/dependencies.py` | `get_current_user`, `require_admin` (403), `require_recruiter`. Token `ver` gate at line 45. |
| `backend/alembic/env.py` | Injects `settings.database_url_sync`; registers models on `Base.metadata`; baseline is raw SQL. |
| `backend/Makefile` | `dev`, `db`, `push`, `deploy`, `deploy-restart`, `deploy-restart-frontend`, `adminer`. |
| `backend/docker-compose.yml` | 10-service prod stack (postgres, redis, web, worker-chatbot ×6, worker-ingest, scheduler, worker-followup, frontend, adminer, caddy). |
| `backend/Caddyfile` | Edge routes for `bot.tingting.vip`. |
| `backend/scripts/create_admin.py` | Bootstrap admin; sync engine psycopg; idempotent `--only-if-no-admins`. |
| `backend/scripts/seed_dev.py` | Truncate + re-insert Vietnamese dev data (LOCAL only). |
| `backend/scripts/prod-env.sh` | Generate `/opt/vfic/.env` (mode 0600) on first deploy; infra secrets random, third-party keys blank. |
| `backend/scripts/benchmark_models.py` | LLM latency/throughput benchmark. |
| `backend/scripts/benchmark_rag.py` | Golden-case RAG retrieval scoring. |
| `frontend/src/main.tsx` | StrictMode + `vite:preloadError` sessionStorage-guarded force-reload. |
| `frontend/src/App.tsx` | Renders `<CRM/>`. |
| `frontend/src/components/atomic-crm/root/CRM.tsx` | `<Admin>` (vendored, not stock react-admin); 8 resources; CustomRoutes; hoisted `QueryClient`; `wrappedAuthProvider`. |
| `frontend/src/components/atomic-crm/providers/rest/api.ts` | HTTP client; JWT in `Authorization: Bearer`; `apiRequest()` 401 retry via `refreshOnce()`; `friendlyApiMessage()` Vietnamese i18n. |
| `frontend/src/components/atomic-crm/providers/rest/dataProvider.ts` | react-admin verb → `/api/v1/{resource}`; custom methods (takeOverConversation, etc.); `RESOURCE_PATH` aliases. |
| `frontend/src/components/atomic-crm/providers/commons/i18nProvider.ts` | `polyglotI18nProvider(() => vietnameseCatalog, "vi", ...)`; `getInitialLocale()` hard-returns `"vi"`. |
| `frontend/src/components/atomic-crm/conversations/messageStore.ts` | Zustand normalized message store (253 LOC); per-conv `Map<id,Message>` + lazily-recomputed sorted array. |
| `frontend/src/components/atomic-crm/conversations/ChatThread.tsx` | Virtualized thread (`virtua` VList); at-bottom detection; double-RAF measure-before-scroll. |
| `frontend/src/lib/vfic/config.ts` | API base resolution: `window.__VFIC__.API_BASE` → `VITE_API_BASE` → "" (same-origin). |
| `frontend/src/lib/vfic/realtimeSocket.ts` | Socket.IO singleton; lazy autoConnect false; websocket-first; JWT re-read on reconnect. |
| `frontend/src/conversations/inbox.css` | Barrel `@import`-ing 10 section files under `conversations/inbox/`. |
| `frontend/vite.config.ts` | Vite 7.3 config; Tailwind v4 plugin; VitePWA autoUpdate (≤5 MiB); manual chunks; dev proxies `/api`, `/realtime`, `/socket.io` → `localhost:8000`. |
| `Makefile` (root) | `dev`, `deploy`, `deploy-backend`, `deploy-frontend`, `adminer`, `seed`, `backup`, `restore`, `backup-full`, `restore-prod`. |
| `scripts/backup-droplet.sh` | Full droplet backup: env + streamed gzipped pg_dump + volume tarballs + Caddy TLS + manifest; embeds restore.sh. |
| `scripts/restore-droplet.sh` | Rebuild stack on fresh droplet from bundle; preflight + best-effort TLS/volume seed; Redis fresh. |
