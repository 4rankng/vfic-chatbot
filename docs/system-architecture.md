# System Architecture

**Last updated:** 2026-09-24
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
│  worker-chatbot (×3) │ worker-persistence │ worker-ingest        │
│  chat turns          │ durable writes     │ KB ingestion,        │
│  webhook_high first, │ off the hot path   │ re-embedding         │
│  recovery second     │ persistence_low    │                      │
│  worker-followup     │ scheduler          │ worker-maintenance   │
│  proactive digests   │ rqscheduler        │ reconcile + dispatch │
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

### 1.2 Fixed static recruitment runtime

The live frontend runtime is intentionally single-tenant and fixed to the
recruitment product surface:

- The backend capability registry remains closed-world source code, but the
  current recruiter console does not fetch executable modules or compile a
  generic pack at runtime. Browser-visible installation data is limited to the
  public runtime manifest projection.
- The frontend boot path mounts one static recruitment runtime bundle
  (`kernel` + `recruitment` contributions) keyed by
  `authority_generation`. When that generation changes, the runtime reset path
  abandons the old Query client/store, closes Socket.IO, clears message and
  adapter state, advances the request epoch, then mounts one fresh recruitment
  generation. Stale responses cannot repopulate the new workspace.
- Installation lifecycle state currently influences safe runtime metadata and
  generation resets only. It does not switch the product to another industry,
  compile arbitrary capability graphs, or enable multi-tenant runtime
  composition in the browser.
- Migration `0044_generic_contact_case_kernel` still preserves dormant generic
  records and APIs on the backend, but those remain outside the live static
  recruitment console until an explicit future product decision reactivates
  them.

### 1.3 Incremental DDD boundary migration

The current rearchitecture is a single-tenant modular-monolith migration. It
does not add tenant identifiers, tenant-scoped repositories, or tenant-aware
runtime abstractions. Multi-tenancy is deferred until 2026-10-22 and requires a
new explicit decision before implementation; it must later consume these
boundaries rather than reshape them prematurely.

The migration is certified at zero exceptions by
`backend/tests/test_architecture_boundaries.py`. Domain modules are
framework-free, application modules depend on domain contracts and ports,
infrastructure implements those ports, and `app/api`, `app/realtime`,
`app/workers`, provider modules, and the React presentation tree remain
adapters. `app/composition` owns cross-context construction; graph-local
construction remains explicit in `app/graph/factories.py`.

Identity/access, project/knowledge, conversation/messaging, recruitment, and
reporting now own their domain values and application entry points. Transport
routers depend on those entry points or infrastructure adapters rather than
importing another context's persistence details. The former
`api/dependencies.py` compatibility export and frontend `lib/vfic` migration
facades have been removed.

Resolved Zalo, MiniMax, OpenRouter, and Facebook OAuth credentials are cached
only in a bounded process-local, namespace-versioned cache. Redis holds the
version counter but never a decrypted credential bundle; an unavailable version
read bypasses the local cache. Facebook OAuth state remains single-use and flow
capsules remain encrypted in Redis behind dedicated state/flow ports. Page
activation and disconnect stage account, encrypted Page token, and audit writes
in one database transaction, then invalidate caches after commit.

Project/knowledge job scheduling and provider construction are application
ports wired to RQ and current graph clients only in `app/composition`.
Conversation delivery, webhook persistence, identity authentication/rate
limits, reporting queries, and integration runtime access follow the same
inward rule. Stable worker enqueue facades, queue names, dotted callable paths,
timeouts, retries, job IDs, and N/N-1 payload decoders remain durable
operational contracts rather than migration scaffolding.

The normative context/package map, inward dependency rules, exact legacy-edge
baseline, runtime contract inventory, and layer-removal ownership are recorded
in [`decisions/ddd-context-boundaries.md`](./decisions/ddd-context-boundaries.md).
`backend/tests/test_runtime_surface_inventory.py` scans the complete backend
application tree and hashes the reviewed HTTP, queue, outbox, and provider
boundaries. Public routes, schemas, queues, realtime events, worker callable
paths, bot policy, and user experience remain compatible.

---

## 2. Request lifecycle — Zalo webhook to sent reply

### 2.0 Agent assignment authority

Agent configuration is channel-adapter scoped, never Project scoped. Exactly one
global default Persona is the fallback for every installed adapter. Zalo
Chatbot, Zalo OA, and Messenger may each store one optional Persona override;
removing an override immediately returns that adapter to the global default.

At turn time the canonical conversation channel identity supplies the provider.
The runtime resolves the effective Persona from that provider before prompt or
follow-up assembly. Project focus independently selects recruiting knowledge,
so changing Project context cannot change the Agent's voice or follow-up policy.
The assembled prompt cache includes the provider scope to prevent one adapter's
override from leaking into another adapter's replies.

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
    Note over WK,DB: ── vacancy authority split ──
    alt generic request for all current jobs
        WK->>WK: bypass FAQ/direct-context and route to required list_active_jobs(top_k=10)
        WK->>DB: load complete ACTIVE Job catalog
        WK->>WK: return deterministic safe list from tool evidence
    else specific company/location/role question and evidence block supports the requested role
        WK->>WK: direct_context_evidence_answer(question, answer)
        WK->>WK: return verbatim Question/Answer block
    else direct-context KB assigned
        WK->>DB: load complete assigned KB text
        WK->>WK: one LLM call over persona + full KB + recent history
    else vacancy-thread factual follow-up
        WK->>WK: combine prior vacancy query + current question
        WK->>WK: stop at a newer named topic boundary; scope salary/details to the same company/recruitment evidence
    else RAG KB assigned
        WK->>WK: route vacancy and document facts to search_knowledge
        WK->>DB: semantic retrieval within active Agent KB projects
        WK->>WK: inject retrieved evidence into one LLM generation
    end
    WK->>WK: assert hiring/details only from published KB evidence or retrieved facts;<br/>otherwise say no verified information was found
    end

    rect rgb(230, 245, 235)
    Note over WK: ── no-LLM fast path (zero model calls) ──
    alt template fast lane (greetings/thanks/help)
        WK->>WK: fast_lane.match(text) → canned reply
    else FAQ semantic bypass (Redis-cached embeddings)
        WK->>WK: faq_bypass.try_answer(text) → canonical KB answer
    else fall through to agent
        WK->>WK: build_system_prompt (persona + active recruitment knowledge projects)
        WK->>WK: route_turn → 8 intents, deterministic (no LLM)
        WK->>DB: lead.context(chat_id) → profile + probing question
        WK->>WK: build_agent_user_text (private history + lead + route hint)
        Note over WK,ZS: prefetch tool for high-confidence routes<br/>(search_knowledge / search_bus_timetable)
        WK->>WK: agent.agent() LLM loop (max 6 iterations)<br/>Redis concurrency semaphore,<br/>tool dispatch = WHERE RAG RETRIEVAL HAPPENS<br/>(search_knowledge, recommend_jobs, get_product_features...)
        WK->>WK: grounding.validate_entity_grounding + id strip — remove hallucinated job IDs and unsupported entity claims
    end
    end

    Note over WK: ── reply boundary ──
    WK->>WK: _finalize_user_visible_reply<br/>strip_think_reasoning only — the answer<br/>ships as generated (no rewrite, no truncation)

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

### 2.2 Private conversation context

Recent chat history, lead profile data, and `search_user_memory` results are private
model context. They may prevent duplicate questions and support a directly relevant
job recommendation, but must never be quoted, summarized, or identified as remembered
information in a user-facing reply. The system prompt, per-turn context, and memory
tool output all carry this boundary so an unrelated or short message cannot trigger a
recap of prior candidate details.

### 2.3 Extraction-owned intent handoff

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
`>= 0.95` **and explicit deterministic evidence for that same negative intent in
the current user message** triggers review. An unsupported negative model label
is downgraded to `uncertain`; candidate/recruitment language therefore cannot
silence future bot turns by itself. Bot output or previously generated notes are
never evidence for the classification, and the intent decision is not written
into candidate notes.

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
| `FAILED` | Zalo definitely rejected the submission. The bot reconciler may re-enqueue a new guarded turn; a recruiter can explicitly retry the same recruiter command from its existing message bubble, returning it to `PENDING` without inserting a second message. |
| `SEND_UNKNOWN` | The provider result was ambiguous (including a crash after submission). Treat as terminal for delivery: investigate if necessary, but do not automatically or manually replay it. |

### Channel-neutral outbound telemetry

Every chatbot send records the same additive adapter fields in
`BotRun.stage_timings`: adapter name, preparation time, provider-request time,
provider attempts, retry/credential-refresh counts and durations, chunk count,
and the final adapter result. The fields contain no message body, recipient ID,
credential, or provider envelope.

The instrumentation only records metadata. It does not change reply content or
delivery flow, and in particular it does not add an OA acknowledgement, typing,
or progress message.

`ZaloChannelSender` selects the concrete Bot or OA adapter, while the graph only
copies this common telemetry contract into the run. A future Facebook Page,
Telegram, or WhatsApp adapter therefore implements the same result metadata
without a graph-runner branch. The admin console also exposes a Facebook
Messenger Settings flow for Page authorization. The performance console groups
p50/p95 provider and end-to-end timing by adapter. Provider-request timing ends
when the provider API responds; candidate-device rendering needs channel
delivery/read receipts and is not inferred.

If the durable outbox recovers a command after a process crash, it writes the
same adapter fields to the linked bot run. When the crash preceded creation of
that run, recovery creates an `outbox_recovery` run with the adapter timing only;
the original webhook-to-send interval is intentionally absent rather than
guessed.

### Admin Agent Thinking trace

Each reactive `BotRun` may carry a versioned `decision_trace` JSON document. Version 2 records one
`model_turn` event after every provider invocation: invocation number, phase, provider/model,
reasoning status, the reasoning text returned by the provider, and the allowlisted names of tools
selected in that same response. MiniMax reasoning is extracted from `<think>` blocks in message
content. OpenRouter reasoning fields are preserved on the assistant message and forwarded unchanged
into the next tool-loop request, so interleaved reasoning remains available to both the provider and
the trace.

The trace does not create separate prompt, candidate-answer, tool-argument, tool-result, or evidence
fields. Provider reasoning is free-form and may repeat conversation context, so it is treated as
sensitive data. That reasoning is preserved in the admin-only trace, not in the user-visible reply.
If a provider returns no reasoning, the event records `not_returned`; the system cannot recover
reasoning the provider withheld. Capture is fail-open and bounded to 64 events, 16 KiB per
reasoning block, and 128 KiB total. Trace detail and per-conversation summaries are admin-only,
loaded on demand, and the trace JSON is cleared after 30 days while the operational `BotRun` row is
retained.

---

## 3. Bot-turn pipeline topology

Documented in `app/graph/runner.py:1-18`; executed in `run_turn` (line 115).
**Note:** the `langgraph` dependency is declared in `requirements` but **no
`StateGraph` / `add_node` is used**. The topology is plain async node
functions composed by hand — "LangGraph-style" in shape only. Document it
honestly as such.

```
load_conversation_state -> typing -> direct_context?
  generic vacancy listing -> required list_active_jobs -> complete ACTIVE Job catalog
  direct_context (available) -> evidence block match -> verbatim Question/Answer block
  direct_context (available) -> no evidence block match -> one grounded LLM call over full assigned KB
  direct_context (not available) -> fast lane / FAQ bypass / routed agent
      vacancy-thread follow-up -> combined vacancy query + current question -> KB answer until a newer named topic boundary
      other agent intent -> scoped tool-calling LLM
      agent (error) -> error_reply
      all user-visible outputs -> _finalize_user_visible_reply (strip provider thinking) -> combine_for_presend
  combine_for_presend -> pre_send_guard -> ownership_ok?
                            yes -> send_message -> log_sent
                            no  -> log_suppressed
```

- **State:** `BotRunState` dataclass (`graph/types.py:21`).
- **Dependencies:** injected via `GraphDeps` (`graph/types.py:32`), wired by
  `build_deps(db)` (`graph/factories.py:65`) which resolves admin-managed
  MiniMax/OpenRouter/Zalo credentials from `integration_settings`.
- **Vacancy authority:** generic requests such as “đang tuyển gì?” bypass FAQ
  and focused direct-context resolution, so vacancy turns go straight to
  required `list_active_jobs(top_k=10)` with no filters. That tool returns a
  bounded catalog built from structured ACTIVE `Job` rows plus active
  DIRECT_CONTEXT project discovery cards, but only when `roles` or `key_roles`
  are explicit on the card. Structured projects are de-duplicated against the
  job rows, the two sources are interleaved in the output, and the discovery
  card projection intentionally leaves salary, shifts, benefits, and follow-up
  details to the full project page. Specific company, location, or role
  questions use the published recruitment KB as the answer source. In
  direct-context mode, the system first tries to return a verbatim `Question:`
  / `Answer:` block from the assigned KB; a canonical answer is only selected
  when any explicit requested role is supported by that block. Otherwise it
  falls through to the direct-context LLM call over that full KB. For
  vacancy-thread factual follow-ups, the runner combines the prior vacancy query
  with the current question until a newer named topic appears, so salary,
  benefits, and other details stay scoped to the same company evidence.
  `search_knowledge` remains the path for document facts. Any LLM-generated
  user-visible reply from the direct-context or routed RAG/agent lanes passes
  through the graph-level reply boundary
  (`runner._finalize_user_visible_reply`) before persistence/delivery, whose only
  transform is `strip_think_reasoning` — the answer is otherwise shipped exactly
  as generated. Template replies, FAQ bypass answers, and evidence blocks remain
  verbatim.
  An empty catalog does not block a real answer from published KB evidence for a
  specific vacancy question.
- **Manifest-scoped runtime handoff:** when a manifest policy is active, the
  runner preserves the same scoped `allowed_tools`, `lookup_query`, and
  vacancy-only `required_tool_args` (`{"top_k": 10}` for `list_active_jobs`)
  while filtering the allowed tools against the manifest's tool registry.
  This keeps the runtime contract identical between the legacy recruitment path
  and the manifest-composed path.
- **Tools** (`graph/tools.py`, `graph/schemas.py`): `TOOL_SCHEMAS` +
  `_dispatch_tool` dispatch by name. The deterministic router prefetches
  `search_bus_timetable` for high-confidence timetable turns and
  `search_knowledge` for high-confidence contact/admin and FAQ-detail turns.
  A factory-agnostic salary target such as “lương 20 triệu” requires
  `compare_income`, which reads a bounded set of active-project income, bonus,
  and cashflow features in one query. Its deterministic renderer lists the
  verified feature text verbatim for each project, preserving distinctions such
  as ordinary monthly income versus annual-average income including bonus; it
  does not infer a yes/no threshold verdict from the first number in a mixed
  compensation field. A numeric target with no project name releases any stale
  project focus; an explicitly named project remains on the focused feature/KB
  path.
  FAQ bypass is deterministic and can abstain on low confidence; when it hits,
  curated FAQ text is returned verbatim. The legacy `path_b_faq` shortcut now
  requires `published_vacancy_evidence=True` before it can return volatile
  vacancy facts; otherwise it abstains. Vacancy-thread detail questions are
  resolved from the same published recruitment evidence rather than from the
  live recommendation catalog, and follow-up scope ends once a newer named topic
  appears. Generic full-list questions bypass FAQ and direct-context shortcuts
  so one KB answer cannot masquerade as the full job catalog.
  `conversations.project_context_state` and `focused_project_id` select
  `EXPLORE` or one `FOCUSED` Project. Focused tool arguments are server-forced
  to that Project slug; model-supplied cross-Project arguments are ignored.
  `EXPLORE` stays RAG-only so retrieval work remains bounded to the current
  query instead of loading every project catalog.
  When a turn is Project-focused and the runtime has an isolated retrieval
  session factory, FAQ-detail prefetch runs `search_knowledge` and
  `get_product_features` in parallel behind bounded semaphores. If that factory
  is unavailable, the same calls run sequentially because the shared
  request-scoped `AsyncSession` is not concurrency-safe.
  `grounding.validate_entity_grounding` compares asserted entity names against
  surfaced evidence using exact slug/display canonicalization, so `LG Display`
  can validate `lg-display` but related projects cannot satisfy one another's
  claims.
- **Tool-loop ceiling:** `max_llm_calls_per_turn` (default 6).
- **Typing heartbeat:** `_typing_heartbeat` sends `typing` to Zalo every 4s
  while a turn is processing (keeps the candidate's typing indicator alive).

---

## 4. RQ queue model (4 queues)

| Queue | Consumer | Job timeout | Backpressure | Purpose |
|---|---|---|---|---|
| `webhook_high` | `worker-chatbot` (×3, priority 1) | 60s (`chat_turn_job_timeout`) | 40 jobs | Live candidate chat turns. |
| `recovery` | `worker-chatbot` (×3, priority 2) | 60s (`chat_turn_job_timeout`) | 40 jobs | Recovered turns re-enqueued by the reconcile sweep; consumed only when `webhook_high` is empty. |
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

### 4.1 Composition roots and runtime lifetimes

Construction is explicit: `app.main.lifespan` owns web-process resources,
`graph/factories.py:build_deps` binds one bot turn, and worker entrypoints bind
one RQ job on the persistent loop from `workers/async_runner.py`. No dependency
container or service locator is used.

Direct and realtime ownership split at the boundary, not by transport. The bot
turn owns the database session, provider call, classification, and outbox write
for that turn. The realtime path owns only a committed, JSON-safe snapshot for
Socket.IO fanout; it never owns ORM objects or business decisions.

| Lifetime | Current owner | Invariant |
|---|---|---|
| Process | FastAPI app, RQ `SimpleWorker`, settings, Socket.IO | Never retains an `AsyncSession` or DB-bound service |
| Event loop | Worker loop, loop-owned engine/sessionmaker, async client pools and locks | Never crosses an event loop or fork boundary |
| Request/job | `get_db()` / `worker_session()` | Closed after the request/job and rolled back on exception |
| Turn | `GraphDeps`, conversation/retrieval/lead/direct-context adapters, Zalo sender | Rebuilt per turn; may reference only that turn's session |
| Transaction | Explicit service commits and rollbacks | Audit, state, outbox, event, and enqueue durability boundaries stay visible; no generic unit of work |
| Session | Repositories/services bound to one `AsyncSession` | Never used concurrently |
| Operation | `worker_session_factory()` contexts | Fresh isolated session for parallel retrieval/profile operations |

MiniMax/OpenRouter clients and the embedder may be cached by credential version.
When credentials change, the next build uses a fresh pool and the prior pool is
retired from new turns. Zalo configuration and sender objects remain per-turn so
a token rotation is visible on the next turn. DB-bound adapters, repositories,
`GraphDeps`, and sessions are never placed in the client cache. Worker shutdown
first cancels and drains pending loop tasks, then closes cached LLM pools,
database engines, and shared HTTP clients on that same loop before closing it.
Web shutdown likewise drains or cancels direct ASGI turns before disposing the
engine and provider clients, so a graceful restart never tears resources out
from under an owned turn.

Queue and event results deliberately remain operation-specific until their
owning context migrates. Chat enqueue returns a backpressure/failure boolean;
category and version ingestion use a stable receipt and can still report
indeterminate acceptance; single-page sync returns an optional receipt with its
own retry policy; persistence and follow-up are best-effort schedules;
reconciliation returns a recovery boolean over already-durable state. Realtime
publishes are separate post-commit snapshot events, not durability claims.
These shapes must not be flattened behind one generic job port.

| Boundary | Commit/enqueue/event guarantee |
|---|---|
| Chat turn enqueue | Backpressure-aware boolean; no claim that rejection was accepted |
| Category/version ingestion | Stable receipt; callers can represent indeterminate acceptance |
| Single-page external sync | Optional receipt with operation-owned retry policy |
| Persistence/follow-up scheduling | Best effort after the owning state transition |
| Reconciliation | Recovery boolean for an already durable conversation/outbox state |
| Conversation realtime | Eager immutable snapshot, post-commit, best effort; never substitutes for audit/outbox durability |
| Audit and outbound outbox | Written in the protected mutation's explicit transaction |

`ConversationEventBus.schedule_realtime` is a post-commit, best-effort event
boundary. It eagerly serializes immutable JSON-safe payload snapshots before
creating the background publish task, never passes ORM objects across the
session boundary, does not delay the committed response, and is cancelled and
drained before its event loop closes. Durable audit and outbound-outbox evidence
remain in the same explicit transactions as their protected mutations; realtime publish
failure cannot roll those transactions back.

---

## 5. Reconcile worker — reliability guarantee

`app/workers/reconcile_worker.py` is **load-bearing**. It guarantees that
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
- Client (`components/atomic-crm/providers/realtime/realtime-socket.ts`):
  singleton, `autoConnect: false`
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

Knowledge mode is selected at the Project boundary. Each Project owns one
`knowledge_bases` row in either `DIRECT_CONTEXT` or `RAG` mode; the same KB cannot
be shared by another Project.

- `DIRECT_CONTEXT` stores one replacement-only file and makes a tool-free LLM
  call with the complete page plus bounded recent conversation history. The raw
  page and deterministic normalized text stay side by side in the database.
  An additive `single_page_external_source_sync_state` row can point at one
  public Google Sheet. The sync worker resolves one exact `gid` from the URL,
  renders the FAQ sheet into deterministic Markdown, and replaces the page
  atomically on success. Manual `Xử lý ngay` syncs and the daily scheduler tick
  both enqueue the same worker path; failures record status on the source row
  and preserve the prior page. The daily tick is cron-pinned via `KB_SYNC_CRON`
  (default `0 20 * * *` UTC = 03:00 ICT).
- `RAG` owns twelve `knowledge_categories`. Immutable
  `knowledge_category_revisions` preserve raw YAML, normalized payloads, a
  deterministic checksum, and recovery metadata (`processing_token`,
  `lease_expires_at`, `attempt_count`, `quality_result`). Revisions are staged
  and embedded before a transaction stores indexed evidence and advances only that
  category's active pointer. Revision claims are atomic and each revision can
  own only one evidence document.
- Category activation is shadow-only until `project.category_authority_started`
  flips during an explicit cutover. Before that flip, retrieval continues to
  read legacy chunks, Jobs, and routes; live category projections are built only at cutover.
- Cutover snapshots the legacy authority, active KB version, category pointers,
  and project-level projection fields. Rollback restores the saved pointers and legacy
  projections even after post-cutover category updates.
- `conversations.project_context_state` and `focused_project_id` select
  `EXPLORE` or one `FOCUSED` Project. Focused tool arguments are server-forced to
  that Project slug; model-supplied cross-Project arguments are ignored.
- The cached agent preamble always carries a compact index of every active Project
  (name, slug, aliases, discovery summary, roles, and location). Current-hiring
  questions never rely on that index or semantic search as vacancy authority:
  generic lists/counts, named factories, named roles, and terse follow-ups in an
  active vacancy thread all require the complete `list_active_jobs(top_k=10)`
  catalog for that turn. Full Project knowledge is loaded only for follow-up details.
- Legacy and category-derived Jobs/routes coexist physically and every candidate/recruiter
  consumer gates them with `category_authority_started`. Category-derived Jobs use presence as availability. Manual status is not an
  authority. A Jobs replacement replays active sibling projections; Transportation
  also replaces Project-scoped `bus_routes` and `bus_stops`.
- Legacy Project document/version ingestion, reindex, and extraction mutations
  are closed after Project-owned knowledge is established. Migration
  `0050_data_ingestion_recovery` adds the lease and cutover snapshot columns that
  back this flow.

- **Store:** pgvector `halfvec` with **HNSW** index on `knowledge_chunks`.
- **Flow:** HNSW candidate generation (`rag_ann_candidates` default 200) →
  **exact vector re-rank** → return top-k. Exact re-rank preserves result
  quality that pure ANN would degrade.
- **Scope:** project-scoped — retrieval is filtered to the candidate's
  project context.
- **Caching:** `rag_cache_enabled` (TTL 300s) + embedding cache (TTL 86400s).
- **Proactive prefetch:** `_should_prefetch_knowledge` (`clients.py:78`) runs
  KB retrieval before the agent call when the turn looks knowledge-bound.
  Focused FAQ-detail turns may also prefetch `get_product_features` alongside
  `search_knowledge` when an isolated retrieval session factory is available;
  EXPLORE turns remain RAG-only.
- **Tools exposed to agent:** `list_active_jobs`, `search_knowledge`,
  `search_user_memory`, `search_bus_timetable`.
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
  - `POST /webhooks/zalo/oa` accepts Zalo's unsigned empty-object verification
    probe. Real OA events are not checked with the stored OA access-token
    secret because it is not webhook-signing material; the explicit risk and
    future cutover gate are recorded in
    `docs/decisions/channel-authenticity-matrix.md`.
  - Acks <1s after the guard chain; enqueues via
    `ZaloWebhookService.handle(..., enqueue=enqueue_chat_run)`. Returns 503
    on enqueue failure so Zalo retries.
- **Credentials** resolved at runtime from
  `IntegrationSettingsService(db).resolve_zalo()` (admin-managed, encrypted
  at rest), falling back to env bootstrap values in dev.

### 11.1 Facebook Messenger settings lifecycle

- **Frontend surface:** `components/atomic-crm/integrations/ZaloIntegrationPage.tsx`
  now includes a separate Messenger section that mounts
  `FacebookMessengerIntegrationPage.tsx` on desktop and mobile.
- **Backend surface:** `backend/app/api/integrations.py` exposes the Messenger
  OAuth lifecycle:
  - `POST /api/v1/admin/integrations/facebook/oauth/start`
  - `GET /api/v1/admin/integrations/facebook/oauth/callback`
  - `GET /api/v1/admin/integrations/facebook/oauth/pages`
  - `POST /api/v1/admin/integrations/facebook/oauth/complete`
  - `POST /api/v1/admin/integrations/facebook/test`
  - `DELETE /api/v1/admin/integrations/facebook`
- **Callback model:** the browser redirect callback is public because the
  provider redirect cannot carry the app JWT. It validates one-time state
  against the initiating admin id and `token_version`, stores an encrypted
  opaque flow capsule in Redis, and redirects back to `/#/settings` with only
  safe status/error flags. The API delegates state and encrypted-capsule storage
  to the Facebook OAuth application boundary; Redis/encryption stay in its
  infrastructure adapter.
- **Session binding:** the page list and completion steps are bound to the same
  admin session and Redis flow key. The completion endpoint atomically consumes
  the flow before any provider side effects, so replays fail with a stale-flow
  error instead of double-activating a Page.
- **Disconnect behavior:** the UI no longer passes a `page_id` query string.
  The server resolves the active Page and disconnects it directly, preserving
  history and keeping the masked Page ID suffix server-owned. Local account
  state, Page-token deletion, and audit are committed atomically before
  best-effort cache invalidation.
- **Scope:** this subsection documents the admin Settings OAuth lifecycle and
  page-management flow. Best-effort remote unsubscribe happens before the
  local disconnect, and the live channel runtime is documented elsewhere in
  this section.

---

## 12. Proactive follow-up

`app/workers/followup_worker.py` fans out per-lead `run_followup_job`:
- Gaps: 6h / 24h / 46h, cap 3 per lead.
- 48h Zalo rule minus 1h margin → 47h window (`PROACTIVE_48H_WINDOW_SECONDS`).
- Per-tick cap 5 (`PROACTIVE_PER_TICK_CAP`); tick every 1800s.
- Opt-out phrase matching (Vietnamese + English substrings, policy constant in
  `recruitment/domain/proactive_policy.py`): `dừng`, `ko quan tâm`, `stop`,
  `unsubscribe`, etc.
- Single `worker-followup` replica (proactive volume is low).

---

## 13. Observability endpoints

| Endpoint | Auth | Returns |
|---|---|---|
| `GET /health` | none | `{"status":"ok","env":...}` |
| `GET /metrics` | none (internal) | RQ queue depths (4 queues), worker count, 7 reconcile canary counters. |
| `GET /health/queue` | none (internal) | Chat-path: queue depth, LLM latency (`_RKEY_INVOKE_MS`), 429s (`_RKEY_429`), fallback count, busy/total workers. |
| `GET /api/v1/admin/performance` | admin | Per-stage p50/p95/p99, adapter comparison, true webhook-to-send latency, route intent, model/tool-call counts, and slow turns. |

No external APM (no Sentry/Datadog). Structured JSON logs to stdout with
`request_id` correlation via ContextVar + `RequestIdMiddleware`.
`uvicorn.access` muted to WARNING.
