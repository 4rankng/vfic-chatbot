# Code Standards

**Last updated:** 2026-07-07

Conventions for the Ting Ting / VFIC miniCRM codebase. Follow these unless a
nearby module has a stronger local pattern; when in doubt, match the
surrounding code.

---

## Backend (Python 3.12, FastAPI, async-first)

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
- **HEAD = `0023_kb_versioned_ingestion`** (7 Jul 2026). 23 migrations + 1
  merge head (`091e7edc9f76_merge...` merging the two `0013_*` heads).
- Run migrations: `docker compose run --rm web alembic upgrade head` (prod,
  5× SSH retry) or `.venv/bin/python -m alembic upgrade head` (local).

### Pydantic v2
- All request/response models in `app/schemas/` are Pydantic v2.
- `Settings(BaseSettings)` uses `SettingsConfigDict(env_file=".env",
  env_file_encoding="utf-8", extra="ignore")`.

### Error handling
- Domain exceptions are mapped to JSON responses by
  `register_domain_exception_handlers(app)` in `main.py`.
- A catch-all `Exception` handler returns a Vietnamese 500 to clients.
- Prefer raising domain exceptions over returning raw `HTTPException` in
  service code. (Some older APIs still use `HTTPException` — convert when
  touched; do not mix styles in one module.)

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
- MiniMax is **always primary** when enabled. OpenRouter is sole only if
  MiniMax is disabled. If neither is enabled, `active_llm_provider` raises.
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
- Resources are registered in `components/atomic-crm/root/CRM.tsx` (8 total:
  leads, conversations, bot_runs, knowledge_sources, projects, personas,
  settings/integrations, users).
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
- `providers/rest/api.ts`:
  - Base URL: `vficConfig.apiBaseUrl` → `window.__VFIC__.API_BASE` →
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
  `components/atomic-crm/conversations/messageStore.ts` (Rocket.Chat-pattern
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
- **`conversations/inbox.css` is a barrel** that `@import`s 11 section files
  under `conversations/inbox/`: `tokens.css` (design tokens), `base.css`,
  `chatops.css`, `features.css`, `personas.css` (largest), `workspace-rail.css`,
  `conversation-list.css`, `chat.css`, `context-drawer.css`, `mobile.css`,
  `typography.css`.
  Design tokens (colors, spacing, radii) live in `tokens.css` — extend there
  rather than scattering literals. Do not reintroduce the old monolithic CSS
  file.
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
- Catalog merge: `vietnameseCrmMessages.ts` over `englishCrmMessages.ts` over
  `ra-language-english` (`allowMissing: true` → English fallback, never raw keys).
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
- **Pure unit tests only** in `backend/tests/` (28 files). No live DB, Redis,
  or external services. `conftest.py` docstring states integration tests were
  moved out.
- `asyncio_mode = "auto"`.
- Coverage: graph (clients, factories, safety), concurrency, LLM semaphore,
  reconcile worker + repository, persistence worker, async runner, scheduler
  registration, lead extraction / chatops, knowledge pipeline / coercion /
  text ingestion, persona + follow-up rules, product features, project
  service, prompts registry, RAG benchmark, schema contracts, webhooks, Zalo
  Bot + OA service, conversation history clear, integration settings.
- Run:
  ```bash
  cd backend
  REDIS_URL=redis://localhost:6380/0 APP_ENV=development \
    .venv/bin/python -m pytest -q --tb=short
  ```
  > Note: the test command pins Redis port **6380** while dev compose exposes
  > **6382** — implies a dedicated test Redis. Flagged in roadmap.

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

## CI notes (template residue — do not trust)
- **No backend CI.** Backend deploys are manual `make push` (docker buildx
  AMD64) + `make deploy` over SSH.
- Frontend `.github/workflows/check.yml` runs ESLint + Prettier + typecheck +
  Vitest unit + Playwright e2e + build (Node 22). Applicable.
- Frontend `.github/workflows/deploy.yml` has a `deploy-supabase` job —
  **Supabase was decommissioned 2026-06-26, so that job is dead.** Inherited
  Atomic CRM template residue. See roadmap.

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
