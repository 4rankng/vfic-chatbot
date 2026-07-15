# Codebase Summary

**Repo:** `git@github.com:4rankng/ChatBotN8N.git` (branch `main`)
**Last updated:** 2026-07-15

A monorepo with two deployable subprojects (`backend/`, `frontend/`) plus
root-level ops scripts. DockerHub images: `franknguyenvd/vfic-backend:latest`
and `franknguyenvd/vfic-frontend:latest` (also tagged `:<git-sha>`).

## Repository layout

```
ChatBot/
├── backend/              FastAPI + RQ workers + Alembic (~42.8k LOC Python)
│   ├── app/
│   │   ├── api/          Routers + auth/capability dependencies
│   │   ├── capabilities/ Closed source-owned pack registry + parity artifacts
│   │   ├── core/         config, db, redis, security,
│   │   │                 logging, errors, cache,
│   │   │                 ratelimit, embedding, vector,
│   │   │                 text                              (~1,600 LOC)
│   │   ├── graph/        runner, clients, factories,
│   │   │                 tools, safety, prompts,
│   │   │                 proactive                         (~5,300 LOC)
│   │   ├── models/       SQLAlchemy 2.x ORM
│   │   ├── schemas/      Pydantic v2
│   │   ├── services/     conversation/, lead/, knowledge/,
│   │   │                 dashboard/, personas/, project/,
│   │   │                 retrieval/, proactive/ + installation,
│   │   │                 generic workflow/contact/case services + flat
│   │   │                 zalo_*, integration_settings, auth (~24,100 LOC)
│   │   ├── workers/      run_worker, chatbot, persistence,
│   │   │                 ingest, followup, reconcile,
│   │   │                 async_runner, scheduler_utils     (~1,600 LOC)
│   │   ├── realtime/     Socket.IO server + bridge         (~300 LOC)
│   │   ├── prompts/
│   │   └── main.py        FastAPI app + lifespan + ASGI wrap
│   ├── alembic/          Hand-written migrations through 0044
│   ├── mock_servers/     zalo_mock.py (local :8788)
│   ├── scripts/          create_admin, seed_dev, prod-env,
│   │                     benchmark_models, benchmark_rag,
│   │                     capture_bus_timetable_golden, loadtest/
│   ├── tests/            Unit + selected disposable PostgreSQL integration lanes
│   ├── docker-compose.yml        10-service prod stack
│   ├── docker-compose.dev.yml    Postgres+Redis+Adminer only
│   ├── Dockerfile        python:3.12-slim, pip install -e .
│   ├── Caddyfile         edge routes for bot.tingting.vip
│   ├── .env.example      committed env template (values blank/dev)
│   └── Makefile          dev / db / push / deploy / adminer
├── frontend/             React Admin SPA (~48.6k LOC TS/TSX)
│   ├── src/
│   │   ├── main.tsx      StrictMode + vite:preloadError guard
│   │   ├── App.tsx       installation gate + dormant runtime compilation
│   │   ├── components/
│   │   │   ├── admin/            vendored shadcn-admin-kit (mutable dep)
│   │   │   ├── ui/               vendored Shadcn primitives (mutable dep)
│   │   │   └── atomic-crm/       THE VFIC app
│   │   │       ├── root/             compiled <CRM> composition + generation reset
│   │   │       ├── capabilities/     static compiler/registry + recruitment adapter
│   │   │       ├── installation/     public runtime bootstrap clients/context
│   │   │       ├── settings/installation/ admin setup wizard
│   │   │       ├── workflows/        blank immutable workflow authoring
│   │   │       ├── contacts/, cases/ dormant generic React Admin resources
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
| Backend `app/services/` | ~24,100 |
| Backend `app/api/` | ~4,000 |
| Backend `app/graph/` | ~5,300 |
| Backend `app/schemas/` | ~2,600 |
| Backend `app/models/` | ~2,600 |
| Backend `app/workers/` | ~1,600 |
| Backend `app/core/` | ~1,600 |
| Backend `app/realtime/` | ~300 |
| **Backend `app/` total** | **~42,800** |
| Frontend `src/` (TS/TSX) | ~48,600 |

## Module map — backend `app/`

| Subdir | Responsibility |
|---|---|
| `api/` | FastAPI routers under `/api/v1` (except `realtime`, `webhooks`). `dependencies.py` holds auth deps. |
| `capabilities/` | Closed-world industry pack/capability definitions, dependency/owner validation, canonical non-executable pack contract, and dormant recruitment delegation descriptor. Database values never select executable imports. |
| `core/` | Cross-cutting infra: config (Pydantic BaseSettings), async DB engine + session, Redis pool, security (JWT/argon2), structured logging + request_id, error handlers, cache, ratelimit, embedding + vector helpers, text utils. |
| `graph/` | The bot-turn pipeline. `runner.py` is the node chain; `clients.py` LLM client wrappers; `factories.py` dependency injection; `tools.py` tool dispatch; `safety.py` fast + LLM safety; `prompts.py`; `proactive/`. |
| `models/` | SQLAlchemy 2.x ORM mirroring the schema, including immutable workflows and generic Contacts/Cases. **Does not generate migrations** — migrations remain hand-written. |
| `schemas/` | Pydantic v2 request/response models. |
| `services/` | Business logic, the largest subpackage. Includes legacy recruitment services, installation authority/setup, and dormant `case_workflow_service`, `contact_service`, and `case_service`. |
| `workers/` | RQ worker entrypoints + async bridge. `run_worker.py` is the container entrypoint. |
| `realtime/` | Socket.IO ASGI server + cross-process emit bridge so workers can push to clients. |
| `prompts/` | Prompt assets. |

## Module map — frontend `src/`

| Subdir | Responsibility |
|---|---|
| `components/admin/` | **Vendored mutable dependency.** shadcn-admin-kit: `admin.tsx`, `data-table.tsx`, `filter-form.tsx`, `simple-form-iterator.tsx`, `file-input.tsx`. |
| `components/ui/` | **Vendored mutable dependency.** Shadcn UI + Radix primitives. |
| `components/atomic-crm/` | **The VFIC app.** All product code lives here. |
| `components/atomic-crm/root/` | `<CRM>` receives one compiled runtime bundle and renders direct React Admin resources/routes; reset code owns Query/store/socket/message generation teardown. |
| `components/atomic-crm/capabilities/` | Static safe module registry, strict pack compiler, canonical backend parity check, and delegation-only recruitment composition. |
| `components/atomic-crm/installation/` | Public runtime manifest parsing, lifecycle context/bootstrap, and setup API clients. |
| `components/atomic-crm/settings/installation/` | PostgreSQL-backed administrator setup wizard; no business configuration is read from browser/env fallbacks. |
| `components/atomic-crm/workflows/` | Blank workflow authoring and structural validation for immutable published versions. |
| `components/atomic-crm/contacts/`, `cases/` | Dormant generic React Admin resources with human selectors and workflow-derived Case fields. |
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
| `backend/app/capabilities/registry.py` | Closed registry resolution and canonical contract hashing; rejects unknown versions, dependency cycles, duplicate owners, and hash drift. |
| `backend/app/capabilities/recruitment_v1_contract.json` | Non-executable backend/frontend parity artifact; canonical hash `2a7c602a...58622d9`. |
| `backend/app/core/config.py` | `Settings(BaseSettings)` + `get_settings()` lru_cache singleton. Boot-time safety checks. `active_llm_provider` / `llm_fallback_enabled` properties. |
| `backend/app/core/security.py` | passlib argon2, python-jose HS256 JWT, `asyncio.to_thread` for crypto. |
| `backend/app/core/db.py` | `create_async_engine(..., pool_pre_ping=True)`, `async_session` (`expire_on_commit=False`), `get_db()` (rolls back on exception). |
| `backend/app/graph/runner.py` | Bot-turn pipeline node chain (`run_turn`). Topology documented in module docstring lines 1-18. |
| `backend/app/graph/types.py` | `BotRunState` (line 21), `GraphDeps` (line 32). |
| `backend/app/graph/factories.py` | `build_deps(db)` (line 65) — resolves admin-managed MiniMax/OpenRouter/Zalo creds. |
| `backend/app/graph/clients.py` | MiniMax / OpenRouter LLM clients; `_chat_for_role` selects one configured provider per client; `_llm_call_with_retry` retries one 429 (line 102); `GeminiEmbedder` (line 127). |
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
| `backend/app/api/dependencies.py` | Auth dependencies plus dormant auth-first `get_active_installation` / `require_capability`; token-version gate remains the identity boundary. |
| `backend/app/services/case_workflow_service.py` | Validate and atomically publish immutable workflow versions/checksums. |
| `backend/app/services/contact_service.py` | Viewer-scoped typed Contact mutations and race-safe configured channel identity resolution. |
| `backend/app/services/case_service.py` | Viewer-scoped, workflow-pinned Case lifecycle, assignment, tags, notes, follow-ups, optimistic updates, and audit writes. |
| `backend/alembic/versions/0044_generic_contact_case_kernel.py` | Additive generic workflow/Contact/Case schema, installation workflow pins, nullable Conversation identity links, immutability and downgrade refusal. |
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
| `frontend/src/App.tsx` | Shows setup unless the public manifest is `ACTIVE + READY`; compiles one runtime generation fail-closed and never remounts the previous Admin after failure. |
| `frontend/src/components/atomic-crm/root/CRM.tsx` | Renders compiled direct React Admin Resources, CustomRoutes, dashboard, navigation, providers, and capability slots. |
| `frontend/src/components/atomic-crm/capabilities/compile-capabilities.ts` | Pure compatibility/collision compiler; no database-selected imports. |
| `frontend/src/components/atomic-crm/root/reset-runtime-state.ts` | Generation-owned Query/store/Socket.IO/Zustand/adapter teardown and stale-response isolation. |
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
