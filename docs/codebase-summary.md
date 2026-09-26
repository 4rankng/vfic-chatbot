# Codebase Summary

**Repo:** `git@github.com:4rankng/vfic-chatbot.git` (branch `main`)
**Last updated:** 2026-09-24

A monorepo with two deployable subprojects (`backend/`, `frontend/`) plus
root-level ops scripts. GHCR images: `ghcr.io/4rankng/tinghire-be:latest`
and `ghcr.io/4rankng/tinghire-fe:latest` (also tagged `:<git-sha>`).

## Repository layout

```
ChatBot/
├── backend/              FastAPI + RQ workers + Alembic (~67.8k LOC Python)
│   ├── app/
│   │   ├── api/          Routers + auth/capability dependencies
│   │   ├── capabilities/ Closed source-owned pack registry + parity artifacts
│   │   ├── core/         config, db, redis, security,
│   │   │                 logging, errors, cache,
│   │   │                 ratelimit, embedding, vector,
│   │   │                 text                              (~2,000 LOC)
│   │   ├── graph/        runner, clients, factories,
│   │   │                 tools, safety, prompts,
│   │   │                 proactive                         (~9,600 LOC)
│   │   ├── models/       SQLAlchemy 2.x ORM (65 tables)
│   │   ├── schemas/      Pydantic v2
│   │   ├── services/     conversation/, lead/, knowledge/,
│   │   │                 dashboard/, personas/, project/,
│   │   │                 retrieval/, proactive/ + installation,
│   │   │                 generic workflow/contact/case services + flat
│   │   │                 project knowledge modes, zalo_*,
│   │   │                 integration_settings, auth (~33,200 LOC)
│   │   ├── workers/      run_worker, chatbot, persistence,
│   │   │                 ingest, followup, reconcile,
│   │   │                 category_worker, async_runner,
│   │   │                 scheduler_utils                   (~2,700 LOC)
│   │   ├── realtime/     Socket.IO server + bridge         (~440 LOC)
│   │   ├── prompts/
│   │   └── main.py        FastAPI app + lifespan + ASGI wrap
│   ├── alembic/          Hand-written migrations through 0054
│   ├── mock_servers/     zalo_mock.py (local :8788)
│   ├── scripts/          create_admin, seed_dev, prod-env,
│   │                     benchmark_models, benchmark_rag,
│   │                     capture_bus_timetable_golden, loadtest/
│   ├── tests/            Unit + selected disposable PostgreSQL integration lanes
│   ├── docker-compose.yml        13-service prod stack
│   ├── docker-compose.dev.yml    Postgres+Redis+Adminer only
│   ├── Dockerfile        python:3.12-slim, pip install -e .
│   ├── Caddyfile         edge routes for bot.tingting.vip
│   ├── .env.example      committed env template (values blank/dev)
│   └── Makefile          dev / db / push / deploy / rollback / adminer
├── frontend/             React Admin SPA (~64.6k LOC TS/TSX)
│   ├── src/
│   │   ├── main.tsx      StrictMode + vite:preloadError guard
│   │   ├── App.tsx       fixed static recruitment console bootstrap
│   │   ├── components/
│   │   │   ├── admin/            vendored shadcn-admin-kit (mutable dep)
│   │   │   ├── ui/               vendored Shadcn primitives (mutable dep)
│   │   │   └── atomic-crm/       THE VFIC app
│   │   │       ├── root/             fixed recruitment <CRM> shell + generation reset
│   │   │       ├── capabilities/     static recruitment runtime bundle modules
│   │   │       ├── installation/     public runtime bootstrap clients/context
│   │   │       ├── workflows/        blank immutable workflow authoring
│   │   │       ├── contacts/, cases/ dormant generic React Admin resources
│   │   │       ├── conversations/    inbox + ChatThread (virtua) + context panel
│   │   │       ├── leads/            kanban + chatops
│   │   │       ├── dashboard/        RecruitingCommandCenter
│   │   │       ├── knowledge/        KnowledgeIngestPanel + project workspace
│   │   │       ├── personas/         persona CRUD + workspace
│   │   │       ├── projects/         ProjectSidebar / BusTimetable / FaqEditor
│   │   │       ├── integrations/     ZaloIntegrationPage + FacebookMessengerIntegrationPage
│   │   │       ├── providers/        dataProvider, authProvider, i18nProvider
│   │   │       ├── layout/           Layout + MobileLayout
│   │   │       ├── login/, settings/, profiles/, misc/, automation/
│   │   │       └── conversations/inbox/   19 CSS section files (barrel = conversations/inbox.css)
│   │   ├── lib/          apiClient.ts, runtime-config.ts, utils.ts,
│   │   │                 vietnameseSearch.ts
│   │   └── hooks/        use-mobile.ts
│   ├── e2e/              Playwright specs (vfic.spec.ts, visual.spec.ts)
│   ├── Dockerfile        node:22 build → nginx:1.27 serve
│   └── package.json      (name "atomic-crm" — historical, not the product)
├── docs/                 this documentation set + DROPLET-BACKUP-RESTORE.md
├── scripts/              backup-droplet.sh, restore-droplet.sh
├── Makefile              dev / deploy / backup / restore (delegates to backend)
└── README.md
```

## LOC breakdown

| Area | LOC |
|---|---|
| Backend `app/services/` | 32,904 |
| Backend `app/graph/` | 9,626 |
| Backend `app/api/` | 4,701 |
| Backend `app/schemas/` | 3,333 |
| Backend `app/models/` | 3,175 |
| Backend `app/workers/` | 2,664 |
| Backend `app/core/` | 1,999 |
| Backend `app/realtime/` | 438 |
| Backend `app/capabilities/` | 328 |
| Backend `app/prompts/` | 47 |
| **Backend `app/` total** | **67,802** |
| Frontend `src/` (TS/TSX) | 64,700 |

Counted 2026-09-24 by walking each directory and summing `wc -l` over its
`*.py` / `*.ts` / `*.tsx` files (physical lines, so blanks and comments are
included), excluding `__pycache__/`, `__screenshots__/` and `node_modules/`.
Re-measure from the tree rather than trusting these numbers once the tree has
moved.

## Module map — backend `app/`

| Subdir | Responsibility |
|---|---|
| `api/` | FastAPI transport routers under `/api/v1` (except `realtime`, `webhooks`). Context-specific dependency adapters are named explicitly; there is no shared compatibility facade. |
| `identity/`, `access/` | Identity/authentication and authorization domain policies, application ports/use cases, and infrastructure adapters. |
| `project_knowledge/` | Project/knowledge domain policies, application scheduling/query/provider ports, and infrastructure adapters. |
| `conversation_messaging/` | Messaging ownership/delivery domain rules, ingress/recovery application ports, and transport persistence adapters. |
| `recruitment/`, `reporting/` | Recruitment domain/application behavior and reporting read-model ports/adapters. |
| `composition/` | Explicit cross-context wiring for messaging, project/knowledge, recruitment, and reporting. Contains construction, not business rules. |
| `capabilities/` | Closed-world industry pack/capability definitions, dependency/owner validation, canonical non-executable pack contract, and dormant recruitment delegation descriptor. Database values never select executable imports. |
| `channels/` | Provider-neutral messaging boundary: ingress/dispatch ports and provider adapters consumed by API ingress, graph dispatch, recruiter delivery and workers. Deliberately not under `graph/`. |
| `installation/` | Single-installation bounded context: lifecycle domain, application ports, and adapters. |
| `integrations/` | Integration-layer application services and adapters (admin runtime, Facebook OAuth). |
| `shared/` | Small inward-facing contracts shared by multiple bounded contexts (`application/`, `domain/`, `infrastructure/`). |
| `core/` | Cross-cutting infra: config (Pydantic BaseSettings), async DB engine + session, Redis pool, security (JWT/argon2), structured logging + request_id, error handlers, cache, ratelimit, embedding + vector helpers, text utils. |
| `graph/` | The bot-turn pipeline. `runner.py` is the node chain; `clients.py` LLM client wrappers; `factories.py` dependency injection; `tools/` the tool implementations; `schemas.py` owns `TOOL_SCHEMAS` + `_dispatch_tool`; `safety.py` structural cleaning; `router.py` the Jev decision router; `prompts.py`; `proactive/`. |
| `models/` | SQLAlchemy 2.x ORM mirroring the schema. Retired universal-platform tables remain mapped for historical migration compatibility. **Does not generate migrations** — migrations remain hand-written. |
| `schemas/` | Pydantic v2 request/response models. |
| `services/` | Business logic, the largest subpackage. Includes recruitment services, project-owned knowledge modes, and installation lifecycle authority used by the admin Settings surface. |
| `workers/` | RQ worker entrypoints + async bridge. `run_worker.py` is the container entrypoint; knowledge category activation/rebuild work has its own worker path. |
| `realtime/` | Socket.IO ASGI server + cross-process emit bridge so workers can push to clients. |
| `prompts/` | Prompt assets. |

## Module map — frontend `src/`

| Subdir | Responsibility |
|---|---|
| `components/admin/` | **Vendored mutable dependency.** shadcn-admin-kit: `admin.tsx`, `data-table.tsx`, `filter-form.tsx`, `simple-form-iterator.tsx`, `file-input.tsx`. |
| `components/ui/` | **Vendored mutable dependency.** Shadcn UI + Radix primitives. |
| `components/atomic-crm/` | **The VFIC app.** All product code lives here. |
| `components/atomic-crm/root/` | `<CRM>` renders the fixed static recruitment runtime bundle; reset code owns Query/store/socket/message generation teardown keyed by authority generation. |
| `components/atomic-crm/capabilities/` | Static single-tenant recruitment runtime modules (kernel + recruitment contributions). There is no live generic runtime compiler or backend-selected import path. |
| `components/atomic-crm/installation/` | Public runtime manifest parsing and lifecycle context/bootstrap. It refreshes safe runtime metadata but does not gate the authenticated recruiter console behind an installer. |
| `components/atomic-crm/providers/` | Transport adapters: react-admin data/auth providers plus the realtime Socket.IO adapter. Shared HTTP/JWT behavior lives in `src/lib/apiClient.ts`. |
| `components/atomic-crm/conversations/` | Layered conversation slice: `presentation -> application -> domain`, with HTTP/realtime/Zustand implementations in `infrastructure/`. CSS remains feature-owned. |
| `components/atomic-crm/leads/` | Kanban board, lead show/edit, chatops actions. |
| `components/atomic-crm/dashboard/` | RecruitingCommandCenter (Vietnamese metric cards). |
| `components/atomic-crm/knowledge/` | Layered knowledge contracts, operations, HTTP/download adapters, and presentation workspaces. |
| `components/atomic-crm/projects/` | ProjectSidebar, ProjectWorkspaceShell, and ProjectKnowledgePanel. Projects own recruiting knowledge, not Agent selection. |
| `components/atomic-crm/personas/` | Persona domain rules, application ports/actions, HTTP adapter, CRUD, and workspace presentation. |
| `components/atomic-crm/integrations/` | ZaloIntegrationPage + FacebookMessengerIntegrationPage (admin only). |
| `lib/` | Shared technical utilities: `apiClient.ts`, `runtime-config.ts`, `utils.ts` (`cn()`), and `vietnameseSearch.ts`. Product behavior stays in feature slices. |

## Project knowledge modes

- `KnowledgeBaseMode` is owned by each Project through its linked KnowledgeBase.
- `DIRECT_CONTEXT` stores one page and preserves both the raw page and the deterministic normalized page; it bypasses chunking, embeddings, and RAG retrieval.
- `RAG` uses 12 independent YAML categories: jobs, compensation, requirements, work schedules, benefits, accommodation, meals, transportation, insurance, application, contacts, and FAQ.
- Category revisions are shadow-prepared first and only become retrieval authority after an explicit Project-wide cutover. Rollback restores the saved pointers and legacy projections even after later category updates.
- Conversation scope uses `EXPLORE` and `FOCUSED`, with `focused_project_id` carrying the active Project when a user switches context explicitly.
- The legacy LG Display KB is linked by migration `0048_project_owned_knowledge_modes`; migration `0050_data_ingestion_recovery` adds lease, attempt, quality-result, and cutover-snapshot columns for the recovery flow.

## Key files table

| File | Purpose |
|---|---|
| `backend/app/main.py` | `FastAPI(title="VFIC API", version="0.1.0", lifespan=lifespan)`. Registers domain exception handlers, CORS (credentials=True, no `*`), request_id middleware, Socket.IO ASGI wrap, rq-scheduler ticks. |
| `backend/app/capabilities/registry.py` | Closed registry resolution and canonical contract hashing; rejects unknown versions, dependency cycles, duplicate owners, and hash drift. |
| `backend/app/capabilities/recruitment_v1_contract.json` | Non-executable backend/frontend parity artifact; canonical hash `2a7c602a...58622d9`. |
| `backend/app/core/config.py` | `Settings(BaseSettings)` + `get_settings()` lru_cache singleton. Boot-time safety checks. `active_llm_provider` / `llm_fallback_enabled` properties. |
| `backend/app/core/security.py` | PyJWT HS256 JWT + passlib argon2, `asyncio.to_thread` for crypto. |
| `backend/app/core/db.py` | `create_async_engine(..., pool_pre_ping=True)`, `async_session` (`expire_on_commit=False`), `get_db()` (rolls back on exception). |
| `backend/app/graph/runner.py` | Bot-turn pipeline node chain (`run_turn`); the topology is documented in the module docstring. |
| `backend/app/graph/types.py` | `BotRunState` and `GraphDeps` dataclasses. |
| `backend/app/graph/factories.py` | `build_deps(db, ...)` — resolves admin-managed MiniMax/OpenRouter/Zalo creds. |
| `backend/app/graph/clients.py` | MiniMax / OpenRouter LLM clients; `_chat_for_role` selects one configured provider per client; `_llm_call_with_retry` retries one 429 then fails over across enabled providers; `GeminiEmbedder`. |
| `backend/app/graph/tools.py` | `TOOL_SCHEMAS` + `_dispatch_tool`. Tools: `search_knowledge`, `search_user_memory`, `search_bus_timetable`. |
| `backend/app/graph/safety.py` | `strip_think_reasoning` — the only user-visible transform at the reply boundary: drops an inline provider ` thinking…` block (complete or truncated) so reasoning never reaches a candidate. The former answer-review layer (`fast_safety_filter`, `DeterministicReplyPolicy`, `truncate_for_chat`) was removed on purpose; the answer ships as generated. |
| `backend/app/graph/clients.py` (answer-completion guard) | A provider that stops at its output cap (`finish_reason=length`) hands back a half-written answer. `MiniMaxAgent.agent` / `.direct` continue it (`_CUT_ANSWER_CONTINUE_INSTRUCTION`, ≤ `_MAX_ANSWER_CONTINUATIONS`), drop a repeated seam, and, if the provider keeps stopping at the cap, drop the dangling tail (`_drop_dangling_tail`) so a candidate never reads a mid-word fragment. Metrics: `answer_continuations`, `answer_continuation_reason`. |
| `backend/app/graph/llm_semaphore.py` | Redis-backed cross-process LLM concurrency semaphore; `LLMThrottled`. |
| `backend/app/api/projects.py` | Project CRUD plus single-page knowledge, 12-category replacement, clear, cutover, and rollback endpoints. |
| `backend/app/services/zalo_sender.py` | `ZaloChannelSender` facade — dispatches per `conv.zalo_channel`. |
| `backend/app/services/zalo_bot_service.py` | `ZaloBotSender`; `send_message`; `send_chat_action`. Base `https://bot-api.zaloplatforms.com`. |
| `backend/app/services/zalo_oa_service.py` | `ZaloOASender`; `POST /v3.0/oa/message/cs`. Base `https://openapi.zalo.me`. |
| `backend/app/services/retrieval/repository.py` | pgvector halfvec HNSW + exact re-rank retrieval. |
| `backend/app/services/knowledge/category_service.py` | Stages, activates, clears, cuts over, rolls back, and derives category revisions for Project-owned RAG categories. |
| `backend/app/workers/run_worker.py` | RQ worker container entrypoint; calls `Worker.clean_registries()` on startup. |
| `backend/app/workers/chatbot_worker.py` | Stable chat-turn RQ entry point (`webhook_high` for live turns, `recovery` for recovered ones, `persistence_low` in dev). |
| `backend/app/workers/reconcile_worker.py` | Reconcile sweep; SETNX non-reentrancy guard and Redis observability counters. |
| `backend/app/workers/followup_worker.py` | Stable proactive follow-up RQ entry point. |
| `backend/app/workers/async_runner.py` | One persistent event loop per worker process (sync RQ → async bridge). |
| `backend/app/realtime/` | Socket.IO server + cross-process emit bridge (264 LOC). |
| `backend/app/api/webhooks.py` | Thin Zalo and Facebook webhook transport; messaging persistence/enqueue behavior is delegated to context adapters and composition. |
| `backend/app/api/auth_dependencies.py` | FastAPI authentication adapter backed by identity application contracts. |
| `backend/alembic/versions/0048_project_owned_knowledge_modes.py` | Additive Project-owned knowledge-mode migration: ownership links, 12 categories, EXPLORE/FOCUSED state, and LG Display backfill guardrails. |
| `backend/alembic/versions/0050_data_ingestion_recovery.py` | Adds durable category processing leases, retry metadata, quality-result storage, and Project cutover snapshot columns. |
| `backend/alembic/env.py` | Injects `settings.database_url_sync`; registers models on `Base.metadata`; baseline is raw SQL. |
| `backend/Makefile` | `dev`, `db`, `push`, `deploy`, `deploy-restart`, `deploy-restart-frontend`, `adminer`. |
| `backend/docker-compose.yml` | 13-service prod stack: postgres, redis, web-blue + web-green (one active colour), worker-chatbot (replicas 3), worker-persistence, worker-ingest, scheduler, worker-followup, worker-maintenance, frontend, adminer, caddy. |
| `backend/Caddyfile` | Edge routes for `bot.tingting.vip`. |
| `backend/scripts/create_admin.py` | Bootstrap admin; sync engine psycopg; idempotent `--only-if-no-admins`. |
| `backend/scripts/seed_dev.py` | Truncate + re-insert Vietnamese dev data (LOCAL only). |
| `backend/scripts/prod-env.sh` | Generate `/opt/vfic/.env` (mode 0600) on first deploy; infra secrets random, third-party keys blank. |
| `backend/scripts/benchmark_models.py` | LLM latency/throughput benchmark. |
| `backend/scripts/benchmark_rag.py` | Golden-case RAG retrieval scoring. |
| `frontend/src/main.tsx` | StrictMode + `vite:preloadError` sessionStorage-guarded force-reload. |
| `frontend/src/App.tsx` | Opens the fixed static recruitment console for every runtime lifecycle and reloads safely if the bundle cannot initialize. |
| `frontend/src/components/atomic-crm/root/CRM.tsx` | Renders the static recruitment runtime's direct React Admin Resources, CustomRoutes, dashboard, navigation, and conversation slots. |
| `frontend/src/components/atomic-crm/capabilities/static-recruitment-runtime.ts` | Builds the fixed static recruitment runtime bundle keyed by installation authority generation. |
| `frontend/src/components/atomic-crm/root/reset-runtime-state.ts` | Generation-owned Query/store/Socket.IO/Zustand/adapter teardown and stale-response isolation. |
| `frontend/src/components/atomic-crm/projects/ProjectKnowledgePanel.tsx` | Project knowledge editor for direct-context pages and per-category RAG replacement. |
| `frontend/src/lib/apiClient.ts` | HTTP client; JWT in `Authorization: Bearer`; `apiRequest()` 401 retry via `refreshOnce()`; Vietnamese error mapping. |
| `frontend/src/components/atomic-crm/providers/rest/dataProvider.ts` | react-admin verb → `/api/v1/{resource}`; custom methods (takeOverConversation, etc.); `RESOURCE_PATH` aliases. |
| `frontend/src/components/atomic-crm/providers/commons/i18nProvider.ts` | `polyglotI18nProvider(() => vietnameseCatalog, "vi", ...)`; `getInitialLocale()` hard-returns `"vi"`. |
| `frontend/src/components/atomic-crm/conversations/infrastructure/message-store.ts` | Zustand normalized message adapter with optimistic/server-echo merge. |
| `frontend/src/components/atomic-crm/conversations/presentation/ChatThread.tsx` | Virtualized thread (`virtua` VList). |
| `frontend/src/components/atomic-crm/knowledge/infrastructure/http-knowledge-adapter.ts` | HTTP adapter for Project single-page and category knowledge operations. |
| `frontend/src/lib/runtime-config.ts` | API base resolution: `window.__VFIC__.API_BASE` → `VITE_API_BASE` → same origin. |
| `frontend/src/components/atomic-crm/providers/realtime/realtime-socket.ts` | Socket.IO transport adapter; lazy connection and JWT re-read on reconnect. |
| `frontend/src/components/atomic-crm/conversations/inbox.css` | Barrel `@import`-ing the 19 section stylesheets under `conversations/inbox/`. |
| `frontend/vite.config.ts` | Vite 7.3 config; Tailwind v4 plugin; VitePWA autoUpdate (≤5 MiB); manual chunks; dev proxies `/api`, `/realtime`, `/socket.io` → `localhost:8000`. |
| `Makefile` (root) | `dev`, `deploy`, `deploy-backend`, `deploy-frontend`, `adminer`, `seed`, `backup`, `restore`, `backup-full`, `restore-prod`. |
| `scripts/backup-droplet.sh` | Full droplet backup: env + streamed gzipped pg_dump + volume tarballs + Caddy TLS + manifest; embeds restore.sh. |
| `scripts/restore-droplet.sh` | Rebuild stack on fresh droplet from bundle; preflight + best-effort TLS/volume seed; Redis fresh. |
