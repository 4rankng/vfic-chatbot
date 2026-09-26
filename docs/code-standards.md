# Code Standards

**Last updated:** 2026-09-24

Conventions for the Ting Ting / VFIC miniCRM codebase. Follow these unless a
nearby module has a stronger local pattern; when in doubt, match the
surrounding code.

---

## Backend (Python 3.12, FastAPI, async-first)

### Project/knowledge layer boundary

- Framework-free policies and value contracts live in
  `app/project_knowledge/domain/`; application ports and orchestration live in
  `app/project_knowledge/application/`.
- FastAPI routes, RQ workers, SQLAlchemy repositories, Redis, provider clients,
  and caches are adapters. They may depend inward; domain/application modules
  must not import them.
- Wire RQ and graph-client implementations only in `app/composition`; the
  `app/project_knowledge` package must never import `app.graph` or `app.workers`.
- Schedule document, version, category, and external-source work through the
  project/knowledge application job facade. Keep the established `ingest` queue,
  worker dotted paths, timeouts, retry policies, job IDs, and operation-specific
  receipt behavior.
- Retrieval SQL and algorithms remain infrastructure. Agent-runtime code consumes
  the project/knowledge query port; conversation and recruitment queries remain
  in their owning slices until their migration phases.

### Async model
- **Async end-to-end** in the web process (uvicorn). RQ workers are sync and
  bridge to async via a **single persistent event loop per worker process**
  (`app/workers/async_runner.py`) — do not spawn a new loop per job.
- SQLAlchemy 2.x **async** API (`create_async_engine`, `AsyncSession`,
  asyncpg) for all application queries.
- A **sync** engine (psycopg) exists **only** for Alembic and one-off
  scripts (`scripts/create_admin.py`, `scripts/seed_dev.py`).
- DB sessions come from `get_db()` (`core/db.py`), which rolls back on
  exception. `async_session` is configured `expire_on_commit=False`.
- `get_settings()` is an `@lru_cache` singleton — never construct `Settings()`
  ad hoc.

### Crypto off the event loop
- All public auth functions are `async` and run argon2 / JWT signing on a
  worker thread via `asyncio.to_thread`. This prevents event-loop stalls under
  concurrent logins. See `app/core/security.py`.

### Database & migrations
- **No raw SQL outside Alembic baseline migrations.** Application code uses
  SQLAlchemy ORM / query builders exclusively.
- Models in `app/models/` **do not generate migrations** — they mirror the
  schema. Alembic baseline `0001` is ~58 KB of raw `op.execute` SQL; later
  revisions are normal Alembic.
- The current Alembic head is the repository source of truth; never hard-code a
  historical head in application logic or documentation.
- Run migrations: `docker compose run --rm web alembic upgrade head` (prod,
  5× SSH retry) or `.venv/bin/python -m alembic upgrade head` (local).

### Pydantic v2
- All request/response models in `app/schemas/` are Pydantic v2.
- `Settings(BaseSettings)` uses `SettingsConfigDict(env_file=".env",
  env_file_encoding="utf-8", extra="ignore")`.

### Error handling
- Domain errors live in `app/shared/domain/errors.py` and are **framework-free**
  (no FastAPI import — enforced by the shared-kernel boundary rule).
  `DomainError` is the base: each subclass declares `status_code` and optional
  response `headers`, and `detail` is the exact JSON payload serialised under
  the response's `detail` key — normally a message string, or a mapping when a
  contract needs structured detail (e.g. `{"errors": [...]}`).
- `register_domain_exception_handlers(app)` in `app/core/errors.py` registers one
  handler against `DomainError`; Starlette resolves handlers by MRO, so every
  subclass — including any added later — is covered automatically. Do not go
  back to registering classes one at a time (that is how a new error gets
  silently forgotten).
- A catch-all `Exception` handler returns a Vietnamese 500 to clients.
- Raise domain errors, **not** raw `HTTPException`. The only sanctioned
  `HTTPException` in the app is `app/core/ratelimit.py`, which raises its own 429
  from inside a dependency.
  Available: `BadRequestError` 400 · `UnauthorizedError` 401 (adds
  `WWW-Authenticate: Bearer`) · `ForbiddenError` 403 · `NotFoundError` 404 ·
  `ConflictError` 409 · `GoneError` 410 · `ValidationError` /
  `DeliveryEligibilityError` 422 · `RateLimitedError` 429 · `UpstreamError` 502 ·
  `InstallationError` (dynamic status + `code`/`lifecycle`/`issues`).
- When a test builds a bare `FastAPI()` around a router, call
  `register_domain_exception_handlers(app)` on it, or domain errors escape as
  raw exceptions instead of HTTP responses.

### The `-strip` directive is load-bearing
- A `-strip` directive in the bot prompt pipeline is **load-bearing**. Never
  remove it or "clean it up" — it controls prompt shaping that production
  relies on. If you don't understand why it's there, ask before changing it.

### Integration credentials
- Zalo / MiniMax / OpenRouter credentials are **admin-managed** in the UI
  (`/admin/integrations`), encrypted at rest with
  `INTEGRATION_SETTINGS_ENCRYPTION_KEY`.
- Runtime code resolves them via
  `IntegrationSettingsService(db).resolve_zalo()` etc., falling back to env
  bootstrap values only in dev.
- Decrypted runtime credential bundles may be cached only in the bounded,
  process-local cache. Redis stores their namespace-version counters, never the
  plaintext bundle. A Redis version-read failure must bypass the local cache so
  stale credentials are not served.
- **Never print secret values.** Documentation may name the env var only.

### Boot-time safety (do not weaken)
`Settings.model_post_init` refuses to boot outside `development` when:
1. `JWT_SECRET` equals the committed default (`dev-only-change-me-...`).
2. `INTEGRATION_SETTINGS_ENCRYPTION_KEY` is unset.
3. `CORS_ORIGINS` contains `*` (credentials are enabled).

### Logging
- Structured JSON to stdout (`app/core/logging.py`).
- `request_id_middleware` stamps `X-Request-Id` via a ContextVar — include it
  when correlating logs.
- `uvicorn.access` is muted to WARNING (the app logger owns access logs).

### LLM client rules
- The admin integration settings choose whether MiniMax and OpenRouter are
  enabled and which enabled provider is selected. There is no per-call provider
  failover: a provider error reaches the normal turn error handling. If neither
  is enabled, `active_llm_provider` raises.
- `_llm_call_with_retry` retries once with jitter on 429, then raises
  `LLMThrottled` → the worker sends a static Vietnamese degradation reply.
- Tool-loop ceiling = `max_llm_calls_per_turn` (default 6).

---

## Frontend (React 19, react-admin 5, TypeScript 5.8 strict)

### TypeScript
- **Strict mode, no `any`.** `tsconfig.app.json` is the source of truth.
- Path alias: `@/*` → `./src/*`.
- Run `npm run typecheck` (`tsc --noEmit --project tsconfig.app.json`).

### React Admin resource conventions
- `CRM.tsx` renders resources from `runtime.resources`, built by
  `capabilities/static-recruitment-runtime.ts` from its fixed `RESOURCE_IDS`
  (8 total: conversations, bot-runs, knowledge-sources, knowledge-bases,
  projects, personas, settings, users).
- **Hash-based routing** (no browser history router).
- `RESOURCE_PATH` aliases (in `dataProvider.ts`): `knowledge_sources` →
  `knowledge/documents`, `projects` → `knowledge/projects`, `personas` →
  `knowledge/personas`.
- The `<Admin>` component is **vendored** at `components/admin/admin.tsx`, not
  stock react-admin. Mobile/desktop share one `<Admin>` (avoids unmount on
  breakpoint cross).

### dataProvider verb mapping
- `components/atomic-crm/providers/rest/dataProvider.ts` maps react-admin
  verbs to `/api/v1/{resource}`.
- Custom methods: `takeOverConversation`, `releaseConversation`,
  `setConversationMode`, `clearConversationHistory`, `markAsRead`,
  `createProfile`, `disableUser`, `enableUser`, `sendHumanReply`.
- `signUp` is **disabled** — users are admin-provisioned only.

### HTTP client & JWT
- `src/lib/apiClient.ts`:
  - Base URL comes from `src/lib/runtime-config.ts`:
    `window.__VFIC__.API_BASE` →
    `VITE_API_BASE` → `""` (same-origin).
  - All paths `/api/v1`.
  - JWT in `Authorization: Bearer` (read via `getAccessToken()`).
  - **Token storage: `localStorage`** under `RaStore.auth.access_token`,
    `RaStore.auth.refresh_token`, `RaStore.auth.identity`. NOT sessionStorage.
  - 401 handling: `apiRequest()` retries once via `refreshOnce()`
    (`POST /api/v1/auth/refresh`) before surfacing 401.
- Error i18n: `friendlyApiMessage()` maps HTTP status → Vietnamese; FastAPI
  422 arrays collapse to a generic Vietnamese message.

### State management
- **TanStack Query** owns server cache. The `QueryClient` is hoisted
  module-level (staleTime 30s, gcTime 24h, networkMode offlineFirst) and
  shared with react-admin's `CoreAdminContext`. Realtime invalidations drive
  freshness.
- **Zustand** for the chat message store:
  `components/atomic-crm/conversations/infrastructure/message-store.ts`
  (Rocket.Chat-pattern
  normalized store). Per-conversation `Map<id,Message>` with lazily-recomputed
  sorted-array cache, O(1) dedup, optimistic-temp + server-echo merge.
  Selectors: `useConversationMessages`, `useConversationFlags`,
  `getNewestRealMessageId`.
- `ra-core` localStorageStore key is `"CRM"`.

### Virtualization
- Use **`virtua`** (`VList`) for virtualized lists — the chat thread
  (`ChatThread.tsx`) depends on it. (Note: `react-virtuoso` is also in deps;
  `virtua` is the active choice for the inbox.)

### Styling — Tailwind v4 CSS-first
- **No `tailwind.config.js`.** Tailwind v4 via `@tailwindcss/vite`, configured
  CSS-first in `src/index.css`.
- `cn()` helper = `clsx` + `tailwind-merge` (`lib/utils.ts`).
- Shadcn UI + Radix primitives.
- `components.json` + `registry.json` drive the vendored Shadcn registry.
- **`conversations/inbox.css` is a barrel** for the inbox sections. Keep rules
  in their owning section; do not reintroduce a monolithic inbox stylesheet.
- **Token ownership:** `src/index.css` owns shared `--workspace-*` semantic
  roles. `conversations/inbox/tokens.css` supplies inbox aliases and
  typography. Feature styles consume the shared roles and may introduce
  feature-scoped aliases only when a local surface requires one (for example,
  settings or performance). The authenticated shell follows the Ting Ting
  console-blue system documented in `docs/design-tokens-graphite-cloud.md`.
  Do not restore superseded warm-paper or graphite/emerald palettes, or scatter
  competing color literals.
- Typography is centralized: define font families, sizes, weights, and line
  heights in `tokens.css`; shared role selectors live in `typography.css`
  (imported last). Do not add one-off page title/card/control font sizes unless
  a component has a real exception, and prefer the `--crm-fs-*`,
  `--crm-fw-*`, and `--crm-lh-*` roles.
- Themes via `<CRM>` props (light/dark logos + themes). Dark mode supported.

### i18n — Vietnamese only
- `providers/commons/i18nProvider.ts`:
  `polyglotI18nProvider(() => vietnameseCatalog, "vi", ...)`. `getInitialLocale()`
  hard-returns `"vi"`. Do not wire other locales.
- Catalog merge: `vietnameseCrmMessages.ts` over `ra-language-english`
  (`allowMissing: true` → library fallback, never raw keys).
- Hard-coded Vietnamese in components is acceptable for one-off strings.
- Diacritic-insensitive search via `lib/vietnameseSearch.ts` (uses the
  `diacritic` package).

### Mutable vendored dependencies
These are **intentionally copy-paste dependencies**; you may edit them
directly, but treat changes with the weight of an upstream fork:
- `src/components/admin/` — shadcn-admin-kit
- `src/components/ui/` — Shadcn UI primitives

> The npm package name is still `atomic-crm` (declared in `package.json`).
> This is a historical artifact from the Atomic CRM template — **not** the
> product name. The product is **Ting Ting / VFIC miniCRM**.

### Path resolution & PWA
- Vite config (`vite.config.ts`): dev proxies `/api`, `/realtime`, `/socket.io`
  (ws: true) → `localhost:8000`. `base: "./"`, sourcemaps on.
- `manualChunks`: react-vendor, ra-vendor, tanstack-vendor, lucide-vendor,
  router-vendor, realtime-vendor, forms-vendor, virtuoso-vendor.
- VitePWA autoUpdate with Workbox precache cap ≤5 MiB.

---

## Testing

### Backend
- **Pure unit tests only** in `backend/tests/` (187 `test_*.py` modules, ~2334
  collected tests). No live DB, Redis, or external services — `conftest.py`
  replaces the Redis singletons with a no-op double, so no infrastructure is
  required to run them. The 25 DB-backed modules live in
  `backend/tests/integration/` and are deselected by default.
- `asyncio_mode = "auto"`.
- Coverage: graph (clients, factories, safety), concurrency, LLM semaphore,
  reconcile worker + repository, persistence worker, async runner, scheduler
  registration, lead extraction / chatops, knowledge pipeline / coercion /
  text ingestion, persona + follow-up rules, product features, project
  service, prompts registry, RAG benchmark, schema contracts, webhooks, Zalo
  Bot + OA service, conversation history clear, integration settings.
- Run (matches the `backend-unit` CI job — no env vars needed):
  ```bash
  cd backend
  .venv/bin/python -m pytest -q -m "not integration" --tb=short
  ```
  The DB-backed integration lane is opt-in (`-m integration`) and needs the
  pgvector dev service:
  `docker compose -f docker-compose.dev.yml up -d postgres`.

### Frontend
- **Vitest 4.1** with two projects:
  - `"app"` — React/DOM unit in Chromium via `@vitest/browser-playwright`
    (headless). Run: `npm run test:unit:app`.
  - `"claude"` — Node integration for `.claude/hooks/*.mjs`. Run:
    `npm run test:unit:claude`.
- **Playwright 1.60** e2e in `e2e/` against `build:e2e` dist served by
  `vite preview :4173`. `fullyParallel: false`. Specs: `vfic.spec.ts`,
  `visual.spec.ts` + snapshots. Run: `npx playwright test`.
- No DB-dependent tests (per project preference).

---

## Commits

- **Conventional commits** (`feat:`, `fix:`, `refactor:`, `docs:`, `chore:`,
  `test:`). Scope optional (`feat(graph): ...`).
- **No AI references** in commit messages or code comments (no "Co-Authored-By:
  Claude", no plan IDs, no phase numbers, no audit labels).
- Keep commits focused; one logical change per commit.
- Never commit secrets, `.env` / `.env.*` (except `.env.example`), `backups/`,
  DB dumps, tokens, or personal data.

### .gitignore highlights
- `.env` / `.env.*` (but `!.env.example`)
- `backups/` (live secrets + DB dumps — never committed)
- `.claude/`, `.omc/`, `CLAUDE.local.md`, `plans/`
- `node_modules/`, `__pycache__/`, `.venv/`, `.pytest_cache/`, `.ruff_cache/`,
  `coverage/`, `graphify-out/`
- Careful: avoid bare `lib/`, `build/`, `dist/` patterns (they would match
  `frontend/src/lib`).

---

## Gate notes
- **There is no CI.** Every gate runs locally, on this machine, orchestrated by
  the repo-root `make release-check`: backend unit (ruff + pytest), backend
  integration smoke, the full backend integration suite, frontend quality
  (lint/typecheck/registry/unit/coverage/build), functional Playwright E2E
  (chromium + Mobile Chrome), `uv lock --check`, exactly one Alembic head with
  `docs/deployment-guide.md` §4 matching it, and the offline golden release gate.
- `make deploy` runs `release-check` first and refuses to build or push an image
  when any gate fails. Run it directly to validate a change without deploying.
- The GitHub Actions workflows (`quality-gates.yml`, `openwiki-update.yml`) were
  removed on 2026-09-26 — deploys are manual anyway, and the gates are the same
  commands run by hand.
- The generated OpenWiki evidence index is refreshed locally with
  `make openwiki` (at the end of a task), never by CI.
- The inherited Atomic CRM workflows under `frontend/.github/` were removed
  (2026-09-13): GitHub only reads root-level workflows, so they never ran for
  this repository.

---

## When you change code

1. Run the narrowest useful test first; broaden when shared contracts change.
2. `npm run typecheck` / `npm run lint` for frontend; `pytest` for backend.
3. Update docs only when user-facing behavior, commands, contracts, or
   architecture changed.
4. For breaking changes, document migration paths in the PR description and
   the relevant `docs/` file.
5. Preserve public contracts unless the change intentionally updates them
   and the user accepted that scope.
