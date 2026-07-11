# Coding Style

> Project-specific coding preferences for the ChatBot (VFIC miniCRM) codebase.
> For the full backend + frontend convention reference, see
> [`../docs/code-standards.md`](../docs/code-standards.md).

## Universal Principles

- **Prefer composition over inheritance.** Use Protocol-based dependency injection (see `backend/app/graph/ports.py`) over class hierarchies.
- **Never introduce global state.** The only module-level singletons allowed are `get_settings()` (`@lru_cache`) and the frontend `QueryClient` (hoisted outside the component to prevent cache wipes).
- **Async functions must support cancellation.** All I/O is async. Crypto (`jose`, `argon2`) runs on `asyncio.to_thread` to avoid blocking the event loop.
- **Avoid duplicated business logic.** If logic appears in two places, extract to a service or shared utility.
- **Prefer explicit types.** No `any` in `frontend/src/components/admin/`, `hooks/`, `lib/` (ESLint error). Backend uses type hints everywhere.
- **No magic numbers.** Extract constants with descriptive names. Proactive follow-up caps, TTLs, and latency budgets live in `config.py` or named constants.
- **Functions should have a single responsibility.** If a function exceeds ~50 lines or mixes concerns, split it.

## Backend (Python 3.12, FastAPI)

- **Async-first.** All DB, Redis, HTTP, and LLM calls are `async def`. Sync wrappers exist only in `workers/async_runner.py` to bridge RQ jobs to asyncio.
- **SQLAlchemy 2.x async.** Use `select()` statements with `AsyncSession`. Never use legacy `Query` API. Sessions use `expire_on_commit=False`.
- **Pydantic v2.** All schemas extend `BaseModel`. Use `model_config = ConfigDict(...)` for config. Validators use `@field_validator` / `@model_validator`.
- **Protocol-based DI.** The graph layer depends on `Protocol` interfaces (`ports.py`: `ConversationPort`, `RetrievalPort`, `LeadContextPort`, `FaqBypassPort`). Concrete wiring in `factories.py:build_deps()`. This enables pure-unit testing with fakes.
- **Domain errors, not HTTP exceptions.** Services raise `NotFoundError`, `ConflictError`, `ForbiddenError`, `UpstreamError` (from `services/errors.py`). The API layer (`api/*.py`) catches and maps to `HTTPException`.
- **Ruff line-length: 100.** Target version: py312. No custom rules — uses ruff defaults.
- **No `print()`.** Use structured logging via `app/core/logging.py`.
- **LLM calls centralized.** All LLM/embedding calls go through `graph/clients.py`. Never call OpenAI/Gemini directly from services or workers.

## Frontend (React 19, TypeScript 5.8 strict)

- **Strict TypeScript.** `noUnusedLocals`, `noUnusedParameters` enabled. `any` is an ESLint error in `components/admin/`, `hooks/`, `lib/`.
- **react-admin resource conventions.** Resources registered in `CRM.tsx` via `<Resource>`. DataProvider maps resource names to API paths (e.g., `knowledge_sources` → `knowledge/documents`).
- **TanStack Query for server state.** Module-level singleton `QueryClient` (`staleTime: 30s`, `gcTime: 24h`, `networkMode: "offlineFirst"`). No persister configured.
- **Zustand for message store only.** `conversations/messageStore.ts` uses a normalized `Map<id, Message>`. Do not add Zustand stores for other domains — use TanStack Query.
- **Tailwind v4 CSS-first.** No `tailwind.config.js`. All tokens defined in `src/index.css` via `@theme inline`. Use `cn()` from `lib/utils.ts` for class merging.
- **shadcn/ui primitives are generated.** `components/ui/` is managed by `npx shadcn`. Do not hand-edit unless vendoring a mutable dep (document why).
- **Vietnamese-only i18n.** All user-facing strings in Vietnamese. Translations in `vietnameseCrmMessages.ts`. English is the base layer, not user-selectable.
- **Path alias.** `@/*` → `./src/*`.
- **Lazy-load secondary routes.** `ProfilePage`, `ForgotPasswordPage` use `React.lazy()` with `RouteErrorBoundary` + `Suspense`.
