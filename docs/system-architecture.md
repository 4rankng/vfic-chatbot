# System Architecture

**Last updated:** 2026-07-09
**Production:** `bot.tingting.vip` (DigitalOcean, 2 vCPU / ~4 GB RAM), Docker
Compose at `/opt/vfic`, Caddy edge.

---

## 1. High-level component diagram

```
                          ┌────────────────────────┐
                          │   Zalo (Bot Platform   │
                          │   + Official Account)  │
                          └───────────┬────────────┘
                                      │ HTTPS webhooks
                                      ▼
┌──────────────────────────────────────────────────────────────────────┐
│                            Caddy (edge, :80/:443)                    │
│   auto Let's Encrypt · HSTS · zstd/gzip · security headers           │
└───────┬──────────────┬──────────────┬──────────────┬─────────────────┘
        │ /webhooks/*  │ /api/*       │ /realtime/*  │ /socket.io/*    │
        │              │              │ (SSE unbuf)  │ (WS upgrade)    │
        ▼              ▼              ▼              ▼
┌──────────────────────────────────────────────────────────────────────┐
│                    FastAPI web (uvicorn, 1 worker)                   │
│   app/main.py · Socket.IO ASGIApp wrap · request_id middleware ·     │
│   domain exception handlers · CORS (credentials, no '*')             │
│                                                                      │
│   Lifespan registers rq-scheduler ticks:                             │
│     - run_proactive_followup_tick   (1800s)                          │
│     - run_reconcile_tick            (60s)    via register_unique_tick│
└───────┬──────────────┬───────────────────────────────────┬───────────┘
        │              │                                   │
        │   enqueue    │  resolve admin-managed creds      │ Socket.IO
        │   (RQ)       │  (MiniMax/OpenRouter/Zalo)         │ conv:<id>
        ▼              ▼                                   ▼
┌────────────────────┐  ┌─────────────────────┐  ┌──────────────────────┐
│  Redis 7           │  │  PostgreSQL 16      │  │  Recruiter console   │
│  - RQ broker       │  │  + pgvector (HNSW)  │  │  (React Admin SPA)   │
│  - pub/sub bridge  │  │  - users, convs,    │  │  Socket.IO client    │
│  - LLM semaphore   │  │    messages, leads, │  │  (websocket-first)   │
│  - rate limit      │  │    knowledge_chunks │  └──────────────────────┘
│    counters        │  │  - integration_secrets (encrypted)           │
│                    │  └─────────────────────┘
└─────────┬──────────┘
          │ RQ jobs
          ▼
┌────────────────────────────────────────────────────────────────────┐
│  RQ workers (sync RQ → persistent async loop via async_runner.py)  │
│                                                                    │
│  worker-chatbot (×6) │ worker-ingest │ worker-followup │ scheduler  │
│   webhook_high       │   ingest      │   followup      │ rqscheduler│
│   persistence_low    │               │                 │            │
└────────────────────────────────────────────────────────────────────┘
          │                                            ▲
          ▼                                            │
┌────────────────────────────────────────────────────────────────────┐
│  LLM providers                                                     │
│   MiniMax M2.7 (agent) / M2.5 (safety)  ── admin-selectable        │
│   OpenRouter (deepseek-v4-flash)        ── admin-selectable        │
│   OpenRouter text-embedding-3-large     ── embeddings (3072-dim)   │
│   Gemini embedding-2                    ── embedding fallback       │
└────────────────────────────────────────────────────────────────────┘
```

---

## 2. Request lifecycle — Zalo webhook to sent reply

```
Candidate ──► Zalo ──► POST /webhooks/zalo/{chatbot,oa}
                            │
                            ▼
  ┌──────────────────────────────────────────────────────────┐
  │ 1. Verify secret (hmac.compare_digest / OA signature)    │
  │ 2. ACK 200 in <1s  (return 503 if enqueue fails → retry) │
  │ 3. ZaloWebhookService.handle(..., enqueue=enqueue_chat_run)│
  └──────────────────────────────────────────────────────────┘
                            │ enqueue_chat_run → RQ webhook_high
                            ▼
  ┌──────────────────────────────────────────────────────────┐
  │ worker-chatbot picks up job (6 replicas, backpressure 40)│
  │  - Worker.clean_registries() on startup requeues stuck   │
  │  - Acquire per-chat DB lock + owner token (TTL 180s)     │
  │  - Record bot PENDING message                           │
  │  - Run bot-turn pipeline (see §3)                       │
  │  - On LLMThrottled → static Vietnamese degradation reply│
  └──────────────────────────────────────────────────────────┘
                            │
                            ▼
  ┌──────────────────────────────────────────────────────────┐
  │ ZaloChannelSender.send → Bot Platform or OA              │
  │  - conv.zalo_channel decides bot vs oa                  │
  │  - ownership + lock owner re-checked at pre_send_guard  │
  │    so a turn started before a take-over/relock is       │
  │    SUPPRESSED, not sent                                 │
  │  - persist SENT / SUPPRESSED + reason                   │
  └──────────────────────────────────────────────────────────┘
                            │
          ┌─────────────────┼──────────────────┐
          ▼                 ▼                  ▼
   persistence_low    Socket.IO emit     Recruiter console
   (lead extraction)  (conv:<id> room)   (realtime thread update)
```

### Sequence — "candidate sends a Zalo message"

```
Candidate    Zalo        Caddy      FastAPI    Redis(RQ)   worker-chatbot   Postgres   MiniMax    Zalo API    Socket.IO   Recruiter
   │          │            │           │           │             │              │          │           │            │            │
   │─message─►│            │           │           │             │              │          │           │            │            │
   │          │─POST/webhook──────────►│           │             │              │          │           │            │            │
   │          │            │           │─verify──► │             │              │          │           │            │            │
   │          │            │           │  secret   │             │              │          │           │            │            │
   │          │◄─200 (<1s)─────────────│           │             │              │          │           │            │            │
   │          │            │           │─enqueue─►│             │              │          │           │            │            │
   │          │            │           │           │─job──────►│              │          │           │            │            │
   │          │            │           │           │             │─lock──────►│          │           │            │            │
   │          │            │           │           │             │─PENDING──►│          │           │            │            │
   │          │            │           │           │             │─typing heartbeat──────►│           │            │            │
   │          │            │           │           │             │             │─load state, RAG──►│           │            │            │
   │          │            │           │           │             │             │          │─agent call──────────►│           │            │
   │          │            │           │           │             │             │          │◄─reply──────────────│           │            │
   │          │            │           │           │             │             │          │─safety call─────────────────────►│           │
   │          │            │           │           │             │             │          │◄─verdict────────────────────────│           │
   │          │            │           │           │             │─ownership re-check─────►│          │           │            │            │
   │          │            │           │           │             │─send─────────────────────────────────►│           │            │            │
   │          │            │           │           │             │─SENT────────────────────►│          │           │            │            │
   │          │            │           │           │             │─emit conv:<id>─────────────────────────────────────────────►│            │
   │          │            │           │           │             │                                                              │─invalidate►│
   │          │            │           │           │             │                                                              │            │◄─thread update
   │◄─reply───│            │           │           │             │                                                              │            │            │
   │          │            │           │           │             │─persistence_low (lead extract)─────────────────────────►│            │            │
```

---

## 3. Bot-turn pipeline topology

Documented in `app/graph/runner.py:1-18`; executed in `run_turn` (line 115).
**Note:** the `langgraph` dependency is declared in `requirements` but **no
`StateGraph` / `add_node` is used**. The topology is plain async node
functions composed by hand — "LangGraph-style" in shape only. Document it
honestly as such.

```
load_conversation_state -> typing -> agent
  agent (error) -> error_reply
  agent (ok)    -> fast_safety_filter -> needs_llm_safety?
                     no  -> combine_for_presend
                     yes -> llm_safety_check -> safe_to_send?
                               yes -> combine_for_presend
                               no  -> retry_rewrite? (attempt<1) -> agent | combine_for_presend
  combine_for_presend -> pre_send_guard -> ownership_ok?
                            yes -> send_message -> log_sent
                            no  -> log_suppressed
```

- **State:** `BotRunState` dataclass (`graph/types.py:21`).
- **Dependencies:** injected via `GraphDeps` (`graph/types.py:32`), wired by
  `build_deps(db)` (`graph/factories.py:65`) which resolves admin-managed
  MiniMax/OpenRouter/Zalo credentials from `integration_settings`.
- **Tools** (`graph/tools.py`, `graph/schemas.py`): `TOOL_SCHEMAS` +
  `_dispatch_tool` dispatch by name. Tools: `search_knowledge` (project-scoped
  semantic retrieval), `search_user_memory`, `search_bus_timetable`.
  `_should_prefetch_knowledge` (`clients.py:78`) proactively runs KB
  retrieval.
- **Tool-loop ceiling:** `max_llm_calls_per_turn` (default 6).
- **Typing heartbeat:** `_typing_heartbeat` sends `typing` to Zalo every 4s
  while a turn is processing (keeps the candidate's typing indicator alive).

---

## 4. RQ queue model (4 queues)

| Queue | Consumer | Job timeout | Backpressure | Purpose |
|---|---|---|---|---|
| `webhook_high` | `worker-chatbot` (×6) | 60s (`chat_turn_job_timeout`) | `chat_queue_max_depth`=40 (503 on overflow) | Chat turns (user-facing latency). |
| `persistence_low` | `worker-chatbot` (same containers) | — | — | Lead / memory extraction after SENT replies. |
| `ingest` | `worker-ingest` | 3600s (`INGEST_JOB_TIMEOUT_SECONDS`) | — | KB digestion / reindex / bus rebuild. |
| `followup` | `worker-followup` (×1) | — | — | Proactive follow-up + reconcile sweep. |

- Container entrypoint: `app/workers/run_worker.py` → calls
  `Worker.clean_registries()` on startup (requeues stuck jobs).
- Async bridge: `workers/async_runner.py` — one persistent event loop per
  worker process.
- rq-scheduler runs in its own container; the FastAPI lifespan also registers
  two unique ticks via `register_unique_tick`:
  `run_proactive_followup_tick` (1800s) and `run_reconcile_tick` (60s).

---

## 5. Reconcile worker — reliability guarantee

`app/workers/reconcile.py` (line 43) is **load-bearing**. It guarantees that
no candidate message is ever silently lost when a worker crashes or restarts
mid-turn.

- Scans every `reconcile_interval_seconds` (60s) for conversations whose
  newest message is unanswered or stuck-PENDING.
- Re-enqueues a fresh chat turn via `enqueue_chat_run`.
- **SETNX non-reentrancy guard** (`reconcile_tick_lock`, ex=300s) prevents
  overlapping sweeps.
- **Per-chat DB lock owner** before touching PENDING rows.
- Writes **7 Redis observability counters** read by `/metrics`.
- Total recovery window ~3-4 min: 60s scan cadence + 120s grace
  (`reconcile_grace_seconds`) before a message is considered stuck.

---

## 6. Data layer

### PostgreSQL 16 + pgvector
- SQLAlchemy 2.x async: `create_async_engine(database_url, pool_pre_ping=True)`.
- `async_session` configured `expire_on_commit=False`. `get_db()` rolls back
  on exception.
- Sync engine (psycopg) for Alembic + scripts only.
- pgvector **halfvec HNSW** for approximate nearest neighbour + **exact vector
  re-rank** preserves result quality (see `services/retrieval/repository.py:160`).
- Embedding dim: 3072 (OpenRouter `text-embedding-3-large` default).

### Tables
users, audit_events, password_reset_otps, projects, companies, jobs,
conversations, messages, bot_runs, leads, lead_events, lead_tags,
follow_up_tasks, personas, integration_settings, kb_versions, kb_text_files,
knowledge_documents, knowledge_chunks (pgvector), worker_feature_catalog,
job_feature_values.

### Redis roles (single instance, 7-alpine, AOF on, 256 MB allkeys-lru)
1. RQ broker (4 queues) + scheduler.
2. Cross-process LLM concurrency semaphore (`llm_concurrency_limit`, 0=disabled).
3. Pub/sub bridge for cross-process Socket.IO emits (worker → web → client).
4. Rate-limit counters (login, forgot-password).
5. Reconcile SETNX non-reentrancy guard + 7 observability counters.
6. RAG result cache (`rag_cache_enabled`, TTL 300s) + embedding cache (TTL 86400s).

Per-chat bot locks are durable conversation-row fields:
`bot_locked_until`, `bot_lock_owner`, and `bot_lock_heartbeat_at`.

> **Redis is not backed up by design** — it is an orphaned-job OOM source.
  Scheduler re-registers its ticks on boot; nothing durable lives here.

---

## 7. Auth

- **JWT (HS256)** via python-jose; password hashing via passlib argon2.
- Replaces Supabase Auth (decommissioned 2026-06-26).
- **Access token:** `access_token_expire_minutes` = 60.
- **Refresh token:** `refresh_token_expire_days` = 14, **rotated on each
  `/refresh`**.
- Both tokens carry a `ver` claim = the user's `token_version`. Bumping it
  (on password change, `auth.py:143`) rejects all prior tokens at the auth
  gate (`dependencies.py:45`) — **revocation without a denylist**.
- Crypto runs on a worker thread via `asyncio.to_thread` (avoids event-loop
  stalls under concurrent logins).
- **Rate limiting** (Redis): login 10/60s/IP; forgot-password 5/300s/IP +
  3/900s/email.
- **Password reset OTP** table: TTL 10 min, attempt limit 5, emails via Resend.
- **Roles:** `admin` | `recruiter` (default recruiter). Auth deps:
  `get_current_user`, `require_admin` (403), `require_recruiter` (admin
  satisfies).

### Client-side
- Tokens in **localStorage** (`RaStore.auth.access_token`,
  `RaStore.auth.refresh_token`, `RaStore.auth.identity`).
- `checkAuth` decodes JWT locally; if `exp*1000 < now`, calls `refreshOnce()`
  before throwing (prevents LogoutOnMount → navigate re-render loop with
  ra-core + RR v7).
- `checkError` clears tokens only on ApiError 401 post-refresh-failure.

> **Open product question:** tokens in localStorage + 14-day refresh token
> means users stay logged in across browser restarts. If session-scoped
> persistence is desired, that's a product decision (see roadmap).

---

## 8. Realtime (Socket.IO)

- Server: `app/realtime/` — the FastAPI app is wrapped by
  `socketio.ASGIApp(_vfic_sio, other_asgi_app=app)` so `/socket.io/` is at the
  ASGI root (Caddy routes `/socket.io/*` → backend with WS upgrade).
- **Rooms:** per-conversation `conv:<id>`. Workers emit via the cross-process
  bridge (Redis pub/sub) so any web process can deliver to any connected
  client.
- Client (`lib/vfic/realtimeSocket.ts`): singleton, `autoConnect: false`
  (connects only after login), websocket-first with polling fallback, JWT
  re-read on reconnect, closed on logout.
- Caddy route `/realtime/*` uses `flush_interval -1` (SSE unbuffered) for the
  legacy `/realtime/events` GET endpoint.

---

## 9. LLM provider architecture

| Path | Model | Role |
|---|---|---|
| MiniMax primary | `MiniMax-M2.7-highspeed` (agent), `MiniMax-M2.5-highspeed` (safety) | Always primary when `MINIMAX_ENABLE=true`. |
| OpenRouter fallback | `deepseek/deepseek-v4-flash` default | Used when MiniMax disabled, or as fallback inside `FallbackLLM`. |
| Embeddings | OpenRouter `text-embedding-3-large` (3072-dim) | Default. |
| Embeddings fallback | Gemini `gemini-embedding-2` | `GeminiEmbedder` (`clients.py:127`). |

- `FallbackLLM` (`clients.py:343`) wraps primary + fallback.
- `_chat_for_role` (`clients.py:444`) returns `FallbackLLM` when both
  MiniMax and OpenRouter are enabled.
- **429 handling:** `_llm_call_with_retry` (`clients.py:102`) retries once
  with jitter, then raises `LLMThrottled` → the worker sends a static
  Vietnamese degradation reply (no off-policy content reaches the candidate).
- **Concurrency:** `llm_concurrency_limit` is a Redis-backed cross-process
  semaphore (`graph/llm_semaphore.py`); `0` = disabled. Separate
  `embed_concurrency_limit` for embeddings.
- `active_llm_provider` property: MiniMax always primary when enabled;
  OpenRouter sole only if MiniMax disabled; raises if neither enabled.

### MiniMax digest pipeline
- `MINIMAX_DIGEST_MODEL` (background-only, generous timeout) digests raw KB
  files into RAG units + builds per-project catalog cards. On timeout the
  pipeline falls back to source-grounded units instead of failing the
  document (see `KnowledgePipeline`).

---

## 10. RAG retrieval

- **Store:** pgvector `halfvec` with **HNSW** index on `knowledge_chunks`.
- **Flow:** HNSW candidate generation (`rag_ann_candidates` default 200) →
  **exact vector re-rank** → return top-k. Exact re-rank preserves result
  quality that pure ANN would degrade.
- **Scope:** project-scoped — retrieval is filtered to the candidate's
  project context.
- **Caching:** `rag_cache_enabled` (TTL 300s) + embedding cache (TTL 86400s).
- **Proactive prefetch:** `_should_prefetch_knowledge` (`clients.py:78`) runs
  KB retrieval before the agent call when the turn looks knowledge-bound.
- **Tools exposed to agent:** `search_knowledge`, `search_user_memory`,
  `search_bus_timetable`.
- **Benchmarks:** `scripts/benchmark_rag.py` (golden-case scoring) and
  `scripts/capture_bus_timetable_golden.py`.

---

## 11. Zalo integration

- **Two API surfaces**, dispatched per-conversation by `conv.zalo_channel`:
  - **Bot Platform** (`services/zalo_bot_service.py`, `ZaloBotSender` line
    241): base `https://bot-api.zaloplatforms.com`, token rides in URL path
    `/bot{TOKEN}/...`. `send_message` line 253, `send_chat_action` line 335
    (typing indicator).
  - **Official Account** (`services/zalo_oa_service.py`, `ZaloOASender` line
    12): base `https://openapi.zalo.me`, `POST /v3.0/oa/message/cs` line 81.
- **Facade:** `ZaloChannelSender` (`services/zalo_sender.py:19`) dispatches.
- **Webhooks** (`app/api/webhooks.py`):
  - `POST /webhooks/zalo/chatbot` (line 34) verifies
    `X-Bot-Api-Secret-Token` via `hmac.compare_digest`. In non-dev with no
    secret → 503 (refuses blind).
  - `POST /webhooks/zalo/oa` (line 71) verifies `X-Zevent-Signature` as
    `sha256(appId+data+timestamp+OAsecretKey)` via `_verify_oa_signature`
    (line 115).
  - Acks <1s after the guard chain; enqueues via
    `ZaloWebhookService.handle(..., enqueue=enqueue_chat_run)`. Returns 503
    on enqueue failure so Zalo retries.
- **Credentials** resolved at runtime from
  `IntegrationSettingsService(db).resolve_zalo()` (admin-managed, encrypted
  at rest), falling back to env bootstrap values in dev.

---

## 12. Proactive follow-up

`app/workers/followup.py` (line 74) fans out per-lead `run_followup_job`:
- Gaps: 6h / 24h / 46h, cap 3 per lead.
- 48h Zalo rule minus 1h margin → 47h window (`PROACTIVE_48H_WINDOW_SECONDS`).
- Per-tick cap 5 (`PROACTIVE_PER_TICK_CAP`); tick every 1800s.
- Opt-out phrase matching (Vietnamese + English substrings, code constant in
  `core/config.py`): `dừng`, `ko quan tâm`, `stop`, `unsubscribe`, etc.
- Single `worker-followup` replica (proactive volume is low).

---

## 13. Observability endpoints

| Endpoint | Auth | Returns |
|---|---|---|
| `GET /health` | none | `{"status":"ok","env":...}` |
| `GET /metrics` | none (internal) | RQ queue depths (4 queues), worker count, 7 reconcile canary counters. |
| `GET /health/queue` | none (internal) | Chat-path: queue depth, LLM latency (`_RKEY_INVOKE_MS`), 429s (`_RKEY_429`), fallback count, busy/total workers. |

No external APM (no Sentry/Datadog). Structured JSON logs to stdout with
`request_id` correlation via ContextVar + `RequestIdMiddleware`.
`uvicorn.access` muted to WARNING.
