# TECH.md — Tech Stack & High-Level Design

> **TingHire** (formerly Ting Ting / VFIC miniCRM) — a Vietnamese recruiting chatbot + recruiter console built on Zalo.
> Production: `bot.tingting.vip` (DigitalOcean 2 vCPU droplet).
>
This document is the single-page summary of *what we run* and *how it fits
together*. For deeper detail, follow the links in §5.

---

## 1. Tech Stack

### Backend (`backend/`) — Python 3.12, async-first

| Layer | Choice | Notes |
|---|---|---|
| Language | **Python ≥ 3.12, < 3.13** | `requires-python = ">=3.12,<3.13"` |
| Framework | **FastAPI** `>=0.115` | async-first; mix of `async def` + thread-offloaded crypto |
| ASGI server | **Uvicorn `[standard]`** `>=0.32` | single worker by design (Dockerfile CMD) — a second doubled cold-boot RSS and widened the listener gap on the 1.9 GiB host |
| ORM | **SQLAlchemy 2.x async** (`asyncpg` `>=0.30`) + sync `psycopg` for Alembic/RQ | `AsyncSession(expire_on_commit=False)` |
| Migrations | **Alembic** `>=1.14` | hand-written (0001–0054, current head `0054_channel_account_projects`), ORM does **not** auto-generate |
| Database | **PostgreSQL 16 + pgvector** (`>=0.3.6`) | HNSW ANN + exact re-rank; `halfvec` for 3072-d embeddings |
| Cache / queue / pubsub | **Redis** `>=5.2,<8.0` | broker, cache, presence, cross-process Socket.IO fan-out |
| Job queue | **RQ** `>=2.0` + **rq-scheduler** `>=0.14` | 6 queues (`webhook_high`, `recovery`, `persistence_low`, `ingest`, `followup`, `maintenance`); **offline only** — never on the answer path |
| Realtime | **python-socketio** `>=5.11` | `AsyncServer` + `AsyncRedisManager` mounted under ASGI |
| Agent brain | **LangGraph-style pipeline** (`app/graph/runner.py`) using `langchain-core` `>=0.3` message types | manual node topology, not the LangGraph engine |
| Turn decisions | **TypeSafe Jev** (`graph/decisions.py`, System One model) | one parallel fan-out call per inbound turn: intent, sort direction, pleasantry kind, context flags, and the candidate's gender (from the profile name + the candidate's own messages) — replaces the keyword router; a confident `male`/`female` fills a blank `leads.gender` so replies address the candidate as anh/chị; admin-managed key in `IntegrationSetting`; disabled/absent/failing → neutral agent fallback |
| LLM clients | **MiniMax + Gemini via OpenRouter**, embeddings via OpenRouter/Gemini (dim 3072) | all calls funneled through `graph/clients.py` |
| Auth | **PyJWT** `>=2.9` (`pyjwt[crypto]`) + **passlib[argon2]** | python-jose was removed — 3.5.0 still pulls `ecdsa` (CVE-2024-23342); `token_version` bumping invalidates sessions |
| Config | **pydantic-settings** `>=2.6` + **Pydantic v2** `>=2.10` | boot-time safety: refuses to start in prod with default `JWT_SECRET` or `*` CORS |
| HTTP client | **httpx** `>=0.28` | async LLM / Zalo / Resend calls |
| Email | **Resend** (transactional) | password-reset sender is a code constant, not config |
| Lint / format | **Ruff** (line 100, py312) | |
| Tests | **pytest + pytest-asyncio** (`asyncio_mode = "auto"`) | pure unit, no infra |

### Frontend (`frontend/`) — React 19 + react-admin, strict TypeScript

| Layer | Choice | Notes |
|---|---|---|
| Language | **TypeScript ~5.8** (strict, `noUnusedLocals`/`noUnusedParameters`) | no `any` in `admin/`, `hooks/`, `lib/` (ESLint error) |
| Framework | **React 19.1** + **ra-core 5** (react-admin headless, `^5.14.7`) | product code imports `ra-core`/`ra-i18n-polyglot` directly, not the `react-admin` meta-package; resources defined in `CRM.tsx` |
| Build | **Vite 7.3** + **vite-plugin-pwa** `^1.2` | manual chunks: react/ra/tanstack/lucide/router/realtime/forms/virtua/zod |
| Styling | **TailwindCSS v4** (CSS-first, no `tailwind.config.js`) + **shadcn/ui** (new-york) + Lucide | tokens in `src/index.css` via `@theme inline` |
| Server state | **TanStack Query v5** | module singleton, `staleTime 30s`, `gcTime 24h` |
| Local state | **Zustand** (message store) + react-admin `localStorageStore` (config) | no global state libs |
| Routing | **react-router v7** (via react-admin) | |
| Realtime | **Socket.IO client** `^4.8` | singleton, lazy connect, per-conversation rooms |
| Forms | **react-hook-form** + **zod v4** | |
| Virtualization | **virtua** `^0.49` | all long lists (conversation thread, dashboard candidate list); `react-virtuoso` is no longer a dependency |
| i18n | **ra-i18n-polyglot** — Vietnamese-first | English as base layer |
| Node | **v22.19.0** (`.nvmrc`), npm + `legacy-peer-deps` | |
| Tests | **Vitest 4** (two projects: `app` Playwright browser, `claude` Node) | |

### Infrastructure

| Piece | Choice |
|---|---|
| Edge / TLS | **Caddy** (`Caddyfile`) |
| Orchestration | **Docker Compose** (13 services on prod, plus the profile-gated `oa-profile-backfill` one-shot) |
| Host | **DigitalOcean droplet**, 2 vCPU / 4 GB — the hard constraint that shapes every decision |
| Backups | Postgres dumps → OneDrive; full-droplet bundle → `backups/<ts>.zip` |
| Secrets | `.env` (gitignored); integration creds encrypted at rest in `IntegrationSetting` |

---

## 2. High-Level Design

### 2.1 Layering

```
Presentation  react-admin SPA (HTTP /api/v1 + Socket.IO)
      ↓
API Layer     app/api/         — FastAPI routers, auth deps, request validation
      ↓
Service Layer app/services/    — business logic, repositories, events
      ↓  Protocol interfaces (graph/ports.py)
Graph Layer   app/graph/       — bot-turn pipeline: agent loop, tools, safety, grounding
      ↓
Data Layer    app/models/      — SQLAlchemy 2.x ORM (65 entities)
      ↓
Infra         app/core/        — DB engine, Redis, config, security
      ↓
Postgres 16 + pgvector     ⟷     Redis (broker / cache / pubsub)
```

**Dependency rule:** API → Services → Models/Core. The graph layer depends on
Protocol interfaces (`ConversationPort`, `RetrievalPort`, `LeadContextPort`,
`FaqBypassPort`) — **never** concrete service classes. Wiring happens in
`factories.py:build_deps()`. This keeps safety/ownership branches unit-testable
with fakes (no API keys needed).

### 2.2 The bot turn (LangGraph-style manual pipeline)

`runner.py` mirrors a LangGraph topology 1:1 via node-named functions:

```
load_conversation_state → typing → agent
   agent (error)  → error_reply
   agent (ok)     → finalize_user_visible_reply        (DeterministicReplyPolicy: regex/length)
   finalize_user_visible_reply → pre_send_guard → ownership_ok?
                           yes → dispatch_claimed_message → record_bot_outcome
                           no  → log_suppressed
```

There is **no LLM safety judge on the answer path**: `GraphDeps.safety` is an unwired
seam with no production caller (`MiniMaxSafety` has no call site). The earlier diagram
in this file showed an `llm_safety_check` node that no longer runs.

Key invariants:
- **Turn routing is a Jev fan-out** (`decisions.py` → `router.route_from_decisions`): one ~300 ms calibrated call replaces the keyword router; on any failure it degrades to the neutral `general/agent` route, never blocking a turn.
- **Grounding** (`grounding.py`) strips hallucinated job IDs before delivery.
- **Pre-send guard** enforces ownership: if a recruiter has taken over the conversation, bot replies are suppressed, not sent.
- **Deadline-aware** — epoch-based turn deadline (`deadline_at_epoch`) survives the FastAPI→RQ process boundary.
- **LLM semaphore** (`llm_semaphore.py`) — cross-process Redis-backed throttle caps concurrent LLM/embed calls to fit the 2 vCPU box.

### 2.3 Retrieval & answer generation

The online answer path is deliberately short, deterministic, and measurable:

1. Receive + normalize message.
2. Load conversation state + candidate profile.
3. Check the exact retrieval cache, then the semantic retrieval cache (`semantic_cache.py`,
   disabled by default) — neither short-circuits generation.
4. Route into a small intent set via **structured outputs** (JSON-schema-constrained).
5. Call retrieval tools (hybrid: PG full-text `tsvector` + pgvector ANN).
6. Re-rank evidence.
7. Generate from **only** the selected evidence (grounded, not chatty).
8. Save trace, update state, enqueue non-urgent follow-ups.

Design choices:
- **Section-based chunking**, not arbitrary token windows — overview / JD / requirements / benefits / salary / location / bus route / FAQ. Cleaner retrieval units, easier citations.
- **RRF (Reciprocal Rank Fusion)** to merge lexical + vector lists.
- **Prompt-prefix caching** — static policies/tool descriptions first, dynamic state last.
- **Retrieval caches** (`semantic_cache.py`, exact-hash `rag:knowledge:*`): these cache the
  *retrieval* result, not the reply, and `semantic_cache_enabled` defaults to **off** —
  measured 24 h in prod: 1 exact hit / 125 lookups, 0 semantic hits. There is no
  response cache, so a repeated FAQ question still pays a full generation.
- **Honesty policy**: if data is missing, the bot says so — never invents schedules, benefits, or requirements.

### 2.4 Background work (RQ, strictly offline)

RQ is kept **off** the synchronous answer path — it protects user-facing latency,
it doesn't sit inside it. Workers (`app/workers/`):

| Worker | Queue | Responsibility |
|---|---|---|
| `chatbot_worker` | `webhook_high`, `recovery` | bot-turn execution (3 replicas; `recovery` drains second) |
| `persistence_worker` | `persistence_low` | durable writes off the hot path |
| `ingest_worker` | `ingest` | KB ingestion, re-embedding, normalization |
| `followup_worker` | `followup` | proactive follow-ups, digests |
| `reconcile_worker` + `outbound_dispatch_worker` | `maintenance` | reconcile sweep + outbound-dispatch ticks |

> ⚠️ **Redis is not backed up.** Cache, presence, semaphore are ephemeral by
> design — never store critical state there. Pub/Sub is at-most-once; use Redis
> Streams when you need durability.

### 2.5 Realtime

- **python-socketio `AsyncServer`** mounted under the FastAPI ASGI app.
- **`AsyncRedisManager`** bridges emits across the API process and RQ worker
  processes — a worker finishes a bot turn and the recruiter console updates live.
- Used for **frontend streaming, events, typing/status** — *not* business logic.

### 2.6 Deployment shape (2 vCPU constraint)

Everything in the HLD is sized for one small droplet. The keep / change / defer:

- **Keep now:** FastAPI, PG + pgvector, Redis, RQ, Docker Compose, Caddy, Socket.IO, recruiter console.
- **Change now:** online path fully async; hybrid retrieval + rerank; semantic cache; structured bus-schedule tables; prompt-prefix caching; multilingual reranking.
- **Defer:** full LangGraph engine, horizontal scaling, external vector DB, cross-service event bus, local model serving, distributed tracing.

### 2.7 Latency budget (design target, not guarantee)

| Stage | Cost |
|---|---|
| Channel normalization + auth | tiny |
| Conversation state load | tiny |
| Exact / semantic cache check | very small |
| Routing | small |
| Hybrid retrieval + filters | small → moderate |
| Reranking | moderate |
| Generation first token | moderate |
| Full answer completion | moderate |

Achievable only by aggressively minimizing context size + prompt-prefix caching +
semantic cache short-circuits.

### 2.8 Observability & release discipline

Every turn logs: **tool inputs/outputs, selected evidence IDs, model choice,
cache hits, final-answer metadata**. Release gates track:

- retrieval hit@k, reranked evidence correctness, factual correctness, groundedness
- recommendation acceptance rate
- p50/p95 time-to-first-token and full-answer latency
- exact + semantic cache hit rates
- prompt-cache read tokens, ANN fallback frequency
- queue depths, stale-posting exposure rate

A **golden dataset** (job-detail lookup, bus schedule, benefit lookup, compare
two jobs, "which job suits me?", multi-turn refinement, Vietnamese paraphrases,
stale/ambiguous/missing-data/safety edges) gates releases.

---

## 3. Key Constraints & Non-Goals

- **2 vCPU / 4 GB droplet** — the binding constraint. No architectural decision is
  final until it has been measured against this box.
- **~100 active conversations** is the phase target, *not* 100 simultaneous LLM
  generations. The box should spend its time waiting on PG/Redis/LLM APIs, not
  burning local CPU.
- **Vietnamese-first** UX — all user-facing strings in Vietnamese.
- **No auto-edits** to: `.env`, `alembic/versions/*`, `docker-compose.yml`,
  `Caddyfile`, `config.py` security defaults, `prompts.py` / `persona.md`,
  `index.css` design tokens, root/backend/frontend `Makefile`s.

---

## 4. Definition of Done (short form)

Build clean · all tests pass · no lint/type errors · docs updated · no orphan
`TODO/FIXME` · migrations reversible & locally tested · no N+1 / blocking I/O /
unbounded lists · no secrets logged · auth enforced · input validated.

---

## 5. Deeper Reading

| Want to know more about | Read |
|---|---|
| Runtime architecture, request lifecycle, queue model | [`docs/system-architecture.md`](docs/system-architecture.md) |
| Retrieval / recommendation / deployment trade-offs (full HLD) | [`docs/HLD.md`](docs/HLD.md) |
| Coding conventions (backend + frontend) | [`docs/code-standards.md`](docs/code-standards.md) |
| Security baseline | [`standards/security.md`](standards/security.md) |
| Performance baseline | [`standards/performance.md`](standards/performance.md) |
| Production stack, deploy, backup/restore | [`docs/deployment-guide.md`](docs/deployment-guide.md) |
| Repository map + key files | [`docs/codebase-summary.md`](docs/codebase-summary.md) |
| Product requirements (FR/NFR) | [`docs/project-overview-pdr.md`](docs/project-overview-pdr.md) |
