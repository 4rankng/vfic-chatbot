# System Architecture

**Last updated:** 2026-07-15
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
│                    FastAPI web (uvicorn, 2 workers)                   │
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
│  worker-chatbot (×1) │ worker-ingest │ worker-followup │ scheduler  │
│ chat turns + persist │   ingest      │   followup      │ rqscheduler│
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

### 1.1 Installation authority foundation (Phase 2)

Phase 2 adds a database-owned installation lifecycle without switching the live
recruitment runtime to universal composition:

- No `installation_state` row means `UNCONFIGURED`. Migration `0042` creates
  `persona_versions`, installation revisions, validation evidence, and the
  singleton state table but inserts no seed, adoption, persona, or active rows.
  The first explicit admin draft creates singleton row `1`.
- Manifest revisions, validation evidence, and persona versions are append-only
  and checksum-pinned. The singleton state row owns current/validated/active
  pointers, an optimistic lock version, and monotonic `authority_generation`;
  activation, rollback, suspend, and resume advance the generation. Revision
  creation must match the state's `expected_lock_version`, so a stale Settings
  save fails with `INSTALLATION_CONFLICT` instead of overwriting a successor.
- Industry packs and capability dependencies are frozen, code-owned metadata.
  Database settings may select allowlisted IDs but cannot supply imports, SQL,
  prompts, tool definitions, or other executable plug-in content. Workflow and
  provider policy inputs are closed typed objects (`extra=forbid`) and contain
  declarative workflow/model choices plus encrypted-integration references,
  never credential values. Locale accepts bounded BCP-47 language tags with an
  optional script/region, and currency is checked against a current ISO-4217
  alphabetic-code allowlist.
- `GET /api/v1/installation/runtime` exposes only allowlisted identity/branding,
  locale, terminology, lifecycle, and capability fields. Persona bodies,
  workflow/provider policy, integration values, and audit evidence stay out of
  the public projection.
- PostgreSQL is authority. Runtime resolution recomputes and checks current
  database evidence before accepting a revision/generation-keyed Redis cache;
  `assert_current()` performs a direct database comparison. Cache writes and
  invalidation are best-effort and cannot change a committed lifecycle result.
  `READY` is derived only after rechecking the current active pointers,
  validation, pack/persona/template/integration evidence, and checksum-pinned
  active-KB state; it is not trusted from the lifecycle string alone.

Activation is deliberately unavailable: the only registered recruitment pack
declares `runtime_ready=false`, so activation fails with
`INSTALLATION_RUNTIME_NOT_READY`. This bounded foundation does **not** make the
image or production deployment universal-ready.

Activation takes the installation authority/state locks and a PostgreSQL
`SHARE MODE` table lock on the recruitment operational tables (`jobs`, `leads`, and
`conversations`) before checking contamination. This closes the current
recruitment count-versus-write race. The pack contract defaults
`runtime_ready=false`; future non-recruitment packs must keep it false until
equivalent guards cover their operational writers.

Two required integrations are explicitly deferred. The existing bot still
consumes the legacy mutable `Persona` projection until the runtime-composition
phase starts reading pinned `PersonaVersion` content. Active-KB publish/rollback
writers are not yet wired to the installation authority barrier and generation
advance; that fencing remains required before activation can be enabled.

### 1.2 Dormant capability compiler and generic kernel (Phase 4)

Phase 4 adds the code-reviewed composition boundary and domain-neutral records
needed by later industry packs, without changing the live recruitment runtime:

- The backend capability registry is closed-world source code. Database state
  may select known pack/capability IDs, but cannot supply modules, imports,
  prompts, tools, routes, or other executable content. The canonical
  non-executable `recruitment@1` contract uses schema `1`, kernel ABI `1`, and
  hash `2a7c602a2e222d14686fca6d86e12da34b0e2ce8ee6b4af32a95af7bd58622d9`.
  Frontend tests consume the checked backend JSON artifact and reject parity
  drift before materializing modules.
- The frontend compiler validates dependencies and rejects unknown or duplicate
  resources, routes, navigation contributions, dashboard owners, and
  conversation slots before mounting React Admin. Compiled `Resource` and
  custom-route elements are direct Admin children. A runtime-generation switch
  abandons the old Query client/store, closes Socket.IO, clears message and
  adapter state, advances the request epoch, then mounts one fresh generation;
  stale responses cannot repopulate the new workspace.
- Migration `0044_generic_contact_case_kernel` adds immutable administrator-
  authored workflow versions, typed Contacts with account-scoped channel
  identities, and Cases pinned to a workflow version/checksum. Case stages,
  transitions, tags, notes, follow-ups, lifecycle, assignment, and bounded
  supplemental attributes are explicit typed authorities rather than generic
  operational EAV. Conversations receive only nullable Contact/channel-identity
  links and projections; there is no inferred Case or Lead backfill.
- Workflow authoring is available to an authenticated administrator before
  activation. Generic Contact/Case APIs require authentication, an active
  installation, and the `conversation` capability. These APIs are therefore
  dormant while activation remains impossible.

Every shipped pack still declares `runtime_ready=false`. Phase 4 does not attach
new guards to the live webhook, workers, Socket.IO rooms, provider dispatch, or
legacy recruitment routers, and it does not change the graph, prompts, safety,
grounding, or tool behavior. The existing setup-persona wire contract still
serializes disabled `hot`, `warm`, and `not_interested` follow-up rule keys. That
recruitment-specific contract is a protected Phase 5 activation blocker: it must
be replaced or deliberately capability-owned before any readiness flip. Phase 6
owns recruitment parity extraction, and Phase 7 owns live authority guards and
the first possible `runtime_ready=true` decision.

---

## 2. Request lifecycle — Zalo webhook to sent reply

```
Candidate ──► Zalo ──► POST /webhooks/zalo/{chatbot,oa}
                            │
                            ▼
  ┌──────────────────────────────────────────────────────────┐
  │ 1. Verify secret (hmac.compare_digest / OA signature)    │
  │ 2. Normalize, deduplicate, and persist inbound            │
  │ 3. Apply mode guard, capture explicit name, acquire lock  │
  │ 4. Enqueue chatbot; no intent-classification work here    │
  │ 5. ACK 200 in <1s (503 on transactional/start failure)   │
  └──────────────────────────────────────────────────────────┘
                            │ RQ job (per-chat DB lease)
                            ▼
  ┌──────────────────────────────────────────────────────────┐
  │ worker-chatbot runs normal and reconciled turns          │
  │  - Worker.clean_registries() on startup requeues stuck   │
  │  - Verify per-chat DB lock + owner token (TTL 180s)      │
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
   persistence_low      Socket.IO emit     Recruiter console
   (extract + intent)   (conv:<id> room)   (realtime thread update)
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

### 2.1 Verified sequence diagram (Mermaid)

> Verified against source on 2026-07-15. File:line anchors point at
> `backend/app/`. Read alongside the simplified ASCII above; this diagram
> adds the two no-LLM fast paths, the four-layer mode/ownership guard,
> and the three-phase message persistence the ASCII omits.

```mermaid
sequenceDiagram
    autonumber
    actor U as Zalo user
    participant Z as Zalo (OA / Bot)
    participant E as Caddy edge
    participant W as FastAPI webhook<br/>(api/webhooks.py)
    participant H as ZaloWebhookService<br/>(services/webhook.py)
    participant DB as Postgres
    participant RQ as Redis / RQ<br/>(queue: webhook_high)
    participant WK as worker-chatbot<br/>(graph/runner.py)
    participant ZS as ZaloChannelSender<br/>(services/zalo_sender.py)
    participant RT as Socket.IO<br/>(realtime/emitter.py)

    U->>Z: message
    Z->>E: POST /webhooks/zalo/{chatbot,oa}
    E->>W: raw body + headers

    Note over W,H: ── adapter preamble ──
    W->>DB: resolve_zalo() (encrypted IntegrationSetting)
    W->>W: verify signature<br/>Bot: shared-secret compare (X-Bot-Api-Secret-Token)<br/>OA: SHA256 HMAC (X-ZEvent-Signature)
    W->>H: handle(payload)

    Note over H: ── normalize and dedup ──<br/>(msg_hash is computed during normalize)
    H->>H: normalize → NormalizedMessage<br/>(return "ignored" if non-text)
    H->>DB: dedup.claim(chat_id, msg_hash)<br/>message_dedup table, 8s window<br/>return "duplicate" if seen
    H->>DB: ensure conversation (upsert Conversation)
    H->>DB: record_inbound → Message WORKER row<br/>bump unread, opt-out check
    H-->>RT: message.created + conversation.updated
    H->>DB: refresh conversation mode<br/>existing HUMAN → stop before extraction
    H->>DB: capture explicit self-reported name<br/>existing lead upsert; no LLM or queue
    H-->>RT: lead.updated (when captured)

    rect rgb(245, 235, 235)
    Note over H,DB: ── mode policy guard layer 1/4 ──
    H->>H: run_start_guard(conv)<br/>HUMAN / CLOSED → "starved_human_mode"<br/>SEMI_AUTO → wait 5min after human inactive<br/>BOT → allow
    end

    rect rgb(245, 235, 235)
    Note over H,DB: ── mode policy guard layer 2/4 ──
    H->>DB: acquire_lock(conv.id)<br/>atomic bot_locked_until UPDATE<br/>return "locked" if held
    end

    H->>Z: fire typing indicator (bot channel only,<br/>fire-and-forget asyncio.create_task)
    H->>RQ: enqueue_chat_run(job)
    Note over H,RQ: backpressure: max_depth check,<br/>503 + lock release on enqueue fail
    W-->>E: 200 ACK {status: "processing"} (< 1s)
    E-->>Z: 200
    Z-->>U: delivered (inbound)

    Note over WK: ══ bot turn (run_turn, line 259) ══

    RQ->>WK: job
    WK->>DB: get conv + refresh
    rect rgb(245, 235, 235)
    Note over WK,DB: ── mode policy guard layer 3/4 ──
    WK->>WK: recheck_ownership(conv, version_at_start, lock_owner)<br/>mismatch → "suppressed" (lock_owner_lost)
    end

    WK->>DB: record_bot_pending → Message BOT PENDING<br/>"Đang soạn trả lời..."
    WK-->>RT: message.created + conversation.updated
    WK->>Z: typing heartbeat (every 4s, bot channel)

    rect rgb(235, 242, 255)
    Note over WK,DB: ── deterministic vacancy guard ──
    alt explicit vacancy question or factual follow-up
        WK->>DB: find_active_jobs (ACTIVE + vacancy_count > 0)
        alt matched
            WK->>WK: render facts from the matching job record
        else no match
            WK->>WK: deterministic "currently not recruiting" reply
        else lookup unavailable
            WK->>WK: availability-error reply; never assert no vacancy
        end
    else other message
        Note over WK: continue to normal response lanes
    end
    end

    rect rgb(230, 245, 235)
    Note over WK: ── no-LLM fast path (zero model calls) ──
    alt template fast lane (greetings/thanks/help)
        WK->>WK: fast_lane.match(text) → canned reply
    else FAQ semantic bypass (Redis-cached embeddings)
        WK->>WK: faq_bypass.try_answer(text) → canonical KB answer
    else fall through to agent
        WK->>WK: build_system_prompt (persona + active-product catalog)
        WK->>WK: route_turn → 8 intents, deterministic (no LLM)
        WK->>DB: lead.context(chat_id) → profile + probing question
        WK->>WK: build_agent_user_text (history + lead + route hint)
        Note over WK,ZS: prefetch tool for high-confidence routes<br/>(search_knowledge / search_bus_timetable)
        WK->>WK: agent.agent() LLM loop (max 6 iterations)<br/>Redis concurrency semaphore,<br/>tool dispatch = WHERE RAG RETRIEVAL HAPPENS<br/>(search_knowledge, recommend_jobs, get_product_features...)
        WK->>WK: grounding.strip — remove hallucinated job IDs
    end
    end

    Note over WK: ── safety ──
    WK->>WK: fast_safety_filter (strip think/code/markdown, truncate)<br/>blocklist_hit → deterministic fallback

    rect rgb(245, 235, 235)
    Note over WK,DB: ── mode policy guard layer 4/4 (closes TOCTOU) ──
    WK->>DB: claim_send — atomic conditional UPDATE<br/>PENDING → SENDING only if<br/>version + lock_owner + TTL all still valid<br/>else → "suppressed"
    end

    alt owned (claim succeeded)
        WK->>ZS: send_message(chat_id, candidate)
        ZS->>ZS: pick Bot vs OA by conv.zalo_channel
        alt OA token-invalid response
            ZS->>ZS: refresh_oa_access_token<br/>(Redis SET NX lock, single-use refresh_token)<br/>retry once
        end
        ZS->>Z: Bot: bot-api.zaloplatforms.com/bot{token}/sendMessage<br/>OA: openapi.zalo.me/v3.0/oa/message/cs<br/>(text chunked at 420 chars)
        Z-->>ZS: send result
        ZS-->>WK: SendResult(ok)
        WK->>DB: record_bot_outcome → Message SENT/FAILED<br/>+ BotRun row (stage_timings JSONB)<br/>clear per-chat lock
        WK-->>RT: message.created + conversation.updated
        Z-->>U: bot reply
        WK->>RQ: enqueue persistence_low<br/>(one LLM call: lead + memory + contact intent)
        RQ->>WK: extract structured contact_intent + confidence
        alt high-confidence non-candidate / spam / bot-testing
            WK->>DB: atomic HUMAN/OPEN/needs_human transition<br/>clear bot lease + fixed SYSTEM note + audit
            WK-->>RT: review note + conversation.updated
            Note over WK,RQ: skip lead/memory writes; future inbound is human-only
        else candidate or uncertain
            WK->>DB: persist lead patch + new memory facts
        end
    else not owned (takeover won the race)
        WK->>DB: record_bot_outcome → SUPPRESSED
    end

    Note over RT: recruiter console receives updates<br/>via room conv:{conversation_id}

    rect rgb(245, 245, 220)
    Note over RQ,WK: ── reconcile recovery (every ~60s) ──
    RQ->>WK: run_reconcile_tick
    WK->>DB: sweep conversations with newest BOT/FAILED<br/>also resolve stale SENDING → SEND_UNKNOWN (never auto-resend)
    WK->>RQ: re-enqueue fresh turn (full re-run, not just HTTP POST)
    end
```

### 2.2 Extraction-owned intent handoff

Contact intent is classified by the existing post-send candidate extraction
call, together with `lead_patch` and `memory_facts`. The webhook/chatbot response
path does not make a second LLM call and does not run a separate intent
classifier. Consequently, the current message receives its normal first reply;
the classification controls future turns only. Every successfully sent
substantive turn is offered to this extraction flow, including FAQ-bypass and
mixed fast-lane messages. A shared normalized pure-pleasantry gate keeps greeting,
thanks, goodbye, and simple help phrases out of the persistence queue entirely.

The extraction result includes the structured fields `contact_intent` and
`intent_confidence`. Only `non_candidate`, `spam`, or `bot_testing` at confidence
`>= 0.95` triggers review. Candidate signals take priority, ambiguous content is
`uncertain`, and bot output or previously generated notes are never evidence for
the classification. The intent decision is not written into candidate notes.

On a positive result, one conditional transaction changes the conversation to
`HUMAN` + `OPEN` with `needs_human=true`, clears any bot lease, and stores a fixed
PII-free system note plus an audit event. Lead and memory writes from that
extraction result are skipped. A deferred extraction job also rechecks the mode
and source conversation version before its LLM call; the final transition repeats
the source-version and non-CLOSED checks atomically. Stale work therefore cannot
override a newer inbound or recruiter action, and work queued after a takeover,
close, or earlier intent handoff exits without spending model tokens. `HUMAN` is
excluded by later webhook bot starts, reconciler recovery, extraction, and
proactive follow-up. An unassigned
thread is read-only in the console until a recruiter clicks **Tiếp quản**.
Returning it to `BOT` is rejected until it has been claimed; an authorized
release clears the review flag and restores chatbot processing.

**Key corrections vs naive "webhook → dedup → normalize → worker → send" sketches**

| Naive sketch | Verified reality |
|---|---|
| `dedup → normalize` | `normalize → dedup` — dedup key is computed during normalize (`webhook.py:111`, `:115`) |
| `verify signature (HMAC)` | Two schemes: Bot = shared-secret compare; OA = SHA256 HMAC (`zalo_oa_signature.py:58`) |
| `apply mode policy` (one step) | Four layers: webhook gate, lock, recheck, atomic `claim_send` (`webhook.py:130`, `:134`, `runner.py:273`, `state.py:329`) |
| `worker: retrieve → generate → policy` | Ten stages incl. two no-LLM fast paths (template + FAQ bypass), routing, lead context, grounding, safety (`runner.py:259-515`) |
| `enqueue → Zalo Send API` | Bot, OA, proactive, and recruiter replies first persist one immutable outbox command, then dispatch it. OA commands retain the inbound quote id; a retry reuses the original message and command. |
| (missing) | The outbound dispatcher recovers PENDING commands (~60s). Retryable failures may be explicitly retried from the same recruiter bubble; terminal `SEND_UNKNOWN` is never resent, including a stale SENDING command after a worker crash. |

### Durable outbound delivery states

The message delivery state and its one-to-one outbox command advance together:
`PENDING → SENDING → SENT | FAILED | SEND_UNKNOWN`. `SUPPRESSED` is a terminal
Bot-policy outcome that makes no provider call.

| State | Meaning and permitted follow-up |
| --- | --- |
| `PENDING` | The message and immutable command committed before provider I/O. The caller may dispatch immediately; the scheduled outbound dispatcher also claims leftover commands every 60 seconds. |
| `SENDING` | One dispatcher has atomically claimed the command and incremented its attempt count. A stale row becomes `SEND_UNKNOWN`, never another send attempt. |
| `SENT` | Zalo confirmed the submission; terminal. |
| `FAILED` | Zalo definitely rejected the submission. A recruiter can explicitly retry this same command from its existing message bubble; the retry returns it to `PENDING` and never inserts a second message. |
| `SEND_UNKNOWN` | The provider result was ambiguous (including a crash after submission). Treat as terminal for delivery: investigate if necessary, but do not automatically or manually replay it. |

---

## 3. Bot-turn pipeline topology

Documented in `app/graph/runner.py:1-18`; executed in `run_turn` (line 115).
**Note:** the `langgraph` dependency is declared in `requirements` but **no
`StateGraph` / `add_node` is used**. The topology is plain async node
functions composed by hand — "LangGraph-style" in shape only. Document it
honestly as such.

```
load_conversation_state -> typing -> vacancy_lookup?
  vacancy_lookup (explicit question/follow-up) -> ACTIVE job match
      matched / no_match / unavailable -> deterministic reply -> combine_for_presend
  vacancy_lookup (not applicable) -> fast lane / FAQ bypass / agent
      agent (error) -> error_reply
      agent (ok)    -> fast_safety_filter -> combine_for_presend
  combine_for_presend -> pre_send_guard -> ownership_ok?
                            yes -> send_message -> log_sent
                            no  -> log_suppressed
```

- **State:** `BotRunState` dataclass (`graph/types.py:21`).
- **Dependencies:** injected via `GraphDeps` (`graph/types.py:32`), wired by
  `build_deps(db)` (`graph/factories.py:65`) which resolves admin-managed
  MiniMax/OpenRouter/Zalo credentials from `integration_settings`.
- **Vacancy authority:** before every fast lane, FAQ bypass, or agent turn,
  direct hiring-existence questions (and factual follow-ups to one) use the
  typed active-job lookup. Only a `jobs` record with `status=ACTIVE` and
  `vacancy_count > 0` may support a current-hiring, company, location, or
  salary claim. `no_match` receives the deterministic no-active-job reply;
  lookup failures receive an availability-error reply rather than a negative
  hiring assertion. Project cards and KB/FAQ retrieval may add context to a
  resolved job, but never establish that a vacancy exists.
- **Tools** (`graph/tools.py`, `graph/schemas.py`): `TOOL_SCHEMAS` +
  `_dispatch_tool` dispatch by name. The deterministic router prefetches
  `search_bus_timetable` for high-confidence timetable turns and
  `search_knowledge` for high-confidence FAQ-detail turns. A successful prefetch
  is injected into a tool-free generation, avoiding an unnecessary
  model→tool→model loop; lookup miss/error retains the original scoped tools.
- **Tool-loop ceiling:** `max_llm_calls_per_turn` (default 6).
- **Typing heartbeat:** `_typing_heartbeat` sends `typing` to Zalo every 4s
  while a turn is processing (keeps the candidate's typing indicator alive).

---

## 4. RQ queue model (4 queues)

| Queue | Consumer | Job timeout | Backpressure | Purpose |
|---|---|---|---|---|
| `webhook_high` | `worker-chatbot` (×1) | 60s (`chat_turn_job_timeout`) | 40 jobs | Interactive and recovered chat turns. |
| `persistence_low` | `worker-persistence` (×1) | — | — | One post-SENT LLM extraction for lead fields, memory facts, and contact intent; high-confidence non-candidate/spam/testing results switch future turns to HUMAN. Isolated from the interactive queue. |
| `ingest` | `worker-ingest` | 3600s (`INGEST_JOB_TIMEOUT_SECONDS`) | — | KB digestion / reindex / bus rebuild. |
| `followup` | `worker-followup` (×1) | — | — | Proactive follow-up, reconcile, and outbound-dispatch sweeps. |

- Container entrypoint: `app/workers/run_worker.py` → calls
  `Worker.clean_registries()` on startup (requeues stuck jobs). It preloads the
  graph and lazy LangChain SDK modules in the parent so forked chat jobs inherit
  them copy-on-write instead of paying the import cost per turn.
- Async bridge: `workers/async_runner.py` — one persistent event loop per
  worker process.
- rq-scheduler runs in its own container; the FastAPI lifespan also registers
  unique ticks via `register_unique_tick`: `run_proactive_followup_tick` (1800s),
  `run_reconcile_tick` (60s), and `run_outbound_dispatch_tick` (60s).

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
Core tables include users, audit events, projects, companies, conversations,
messages, outbound commands, bot runs, personas/persona versions, integration
settings, installation revisions/validations/setup/state, and versioned
knowledge/provenance records. The legacy recruitment adapter continues to own
jobs, leads, lead events/tags, follow-up tasks, and worker/job feature tables.

The dormant generic kernel adds `case_workflow_versions`,
`case_workflow_stages`, `case_workflow_transitions`, `case_tag_definitions`,
`contacts`, `contact_channel_identities`, `cases`, `case_tag_assignments`,
`case_notes`, and `case_followups`. These tables are schema-only after migration:
`0044` inserts no workflow, stage, tag, Contact, Case, customer, template,
persona, credential, or sample row.

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
| MiniMax | `MiniMax-M2.7-highspeed` (agent), `MiniMax-M2.5-highspeed` (safety) | Selected when `LLM_DEFAULT_PROVIDER=minimax`, or when it is the only enabled generation provider. |
| OpenRouter | `deepseek/deepseek-v4-flash` default | Selected when `LLM_DEFAULT_PROVIDER=openrouter`, or when it is the only enabled generation provider. |
| Embeddings | OpenRouter `text-embedding-3-large` (3072-dim) | Default. |
| Embeddings fallback | Gemini `gemini-embedding-2` | `GeminiEmbedder` (`clients.py:127`). |

- `_chat_for_role` resolves one configured generation provider when the client
  is built. It does not retry a failed turn through another LLM provider.
- **429 handling:** `_llm_call_with_retry` (`clients.py:102`) retries once
  with jitter, then raises `LLMThrottled` → the worker sends a static
  Vietnamese degradation reply (no off-policy content reaches the candidate).
- **Concurrency:** `llm_concurrency_limit` is a Redis-backed cross-process
  semaphore (`graph/llm_semaphore.py`); `0` = disabled. Separate
  `embed_concurrency_limit` for embeddings.
- `active_llm_provider` property: selects `LLM_DEFAULT_PROVIDER` when that
  provider is enabled; otherwise selects the remaining enabled provider; raises
  if neither is enabled.

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
| `GET /api/v1/admin/performance` | admin | Per-stage p50/p95/p99, true webhook-to-send latency, route intent, model/tool-call counts, and slow turns. |

No external APM (no Sentry/Datadog). Structured JSON logs to stdout with
`request_id` correlation via ContextVar + `RequestIdMiddleware`.
`uvicorn.access` muted to WARNING.
