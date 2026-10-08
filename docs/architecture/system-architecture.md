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
│   Lifespan registers rq-scheduler ticks (queue: maintenance):        │
│     - run_reconcile_tick            (60s)    via register_unique_tick│
│     - run_outbound_dispatch_tick    (60s)                             │
│     - email digest (cron)                                            │
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
│  worker-chatbot (×4) │ worker-persistence │ worker-ingest        │
│  chat turns          │ durable writes     │ KB ingestion,        │
│  webhook_high first, │ off the hot path   │ re-embedding         │
│  recovery second     │ persistence_low    │                      │
│  worker-category     │ scheduler          │ worker-maintenance   │
│  KB classification   │ rqscheduler        │ reconcile + dispatch │
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
  The first explicit admin draft creates singleton row `1`. Migration `0066`
  has since dropped `persona_versions` (with `personas` and
  `adapter_persona_assignments`), because the persona is a code constant.
- Manifest revisions and validation evidence are append-only and
  checksum-pinned. The singleton state row owns current/validated/active
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
  active-KB state; it is not trusted from the lifecycle string alone. The
  persona leg of that evidence is now a hash of the persona the running code
  ships (`current_persona_checksum()` in
  `app/services/installation/validation.py`), not a stored row compared with
  itself — the same fail-closed guarantee, with the drift source removed.

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

Two required integrations are explicitly deferred. The bot reads its persona
directly from the code constant in `backend/app/prompts/vfic_persona.py`
(re-exported as `AGENT_SYSTEM_PROMPT`), not from a mutable database projection
and not from a pinned `PersonaVersion` row — there is no provider-level persona
override left to resolve. Active-KB publish/rollback writers are not yet wired
to the installation authority barrier and generation advance; that fencing
remains required before activation can be enabled.

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
in [`decisions/ddd-context-boundaries.md`](../decisions/ddd-context-boundaries.md).
`backend/tests/test_runtime_surface_inventory.py` scans the complete backend
application tree and hashes the reviewed HTTP, queue, outbox, and provider
boundaries. Public routes, schemas, queues, realtime events, worker callable
paths, bot policy, and user experience remain compatible.

### 1.3.1 Maintaining the existing boundaries

- HTTP and Socket.IO authenticate through the same identity authenticator.
  Realtime code cannot import API transport dependencies; its event adapter
  retains the existing public event names and checks entity ID types before
  calling viewer-scope queries.
- Project KB category identity lives in
  `app/project_knowledge/domain/category.py`; ordered authoring metadata and
  lookup live in `domain/category_catalog.py`. Schema, ingest, export,
  projection and retrieval consumers share that registry. To add a category,
  add its identity, definition, typed document model and Markdown template;
  registry regressions require exact schema coverage and ordering. Field and
  template names derive from the category ID.
- Importing a leaf knowledge helper does not load the full ingestion and
  persistence graph. The package retains its established public exports and
  loads each export's owner when requested.
- Recruitment ports distinguish an unresolved lead lookup from a completed
  lookup with no record. Bot stages reuse completed reads, including misses;
  independent adapter callers retain their repository fallback. A successful
  name write refreshes that context; a failed refresh marks it unresolved so
  the next consumer can retry and observe the committed write.
- Graph import guards scan nested tools as well as stage modules. Shared
  TingTing verification policy belongs in `app/integrations/tingting/domain.py`,
  so a tool does not import a concrete HTTP/persistence service for a constant.
- Frontend dependency checks enforce `atomic-crm → admin → ui` for production
  modules. Category and discovery-card mutations use synchronous exclusion
  while a request is in flight, with context-aware release and retry behavior.
  React state remains the display of that operation rather than its lock.

---

## 2. Request lifecycle — Zalo webhook to sent reply

### 2.0 Agent identity is code-owned

Agent configuration is channel-adapter scoped, never Project scoped. There is
exactly one persona — the code constant `DEFAULT_PERSONA_BODY_MD` in
`backend/app/prompts/vfic_persona.py`, re-exported as `AGENT_SYSTEM_PROMPT` — and
every installed adapter speaks it. The `persona-assignments` override table and
the persona CRUD API were removed, so no adapter and no operator can give one
channel a different voice.

At turn time the canonical conversation channel identity supplies the provider.
Project focus independently selects recruiting knowledge, so changing Project
context cannot change the Agent's voice. `app/graph/context.py` builds the system
prompt for the agent lane and `app/graph/direct_context.py` for the direct-context
lane; both append `IDENTITY_AND_OPENING_RULES` after the persona body, so the
rule that the bot never presents itself as an AI, never opens with a
self-introduction, and never asks for a mobile number before delivering real
value cannot be lost by refactoring either lane.

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
    H->>DB: ensure conversation (upsert Conversation;<br/>created rows eagerly load contact +<br/>channel_identity for realtime serialization)
    H->>DB: record_inbound → Message WORKER row<br/>INSERT .. ON CONFLICT DO NOTHING:<br/>a redelivery past the dedup window returns<br/>the durable row instead of 500ing<br/>bump unread, opt-out check
    H-->>RT: message.created + conversation.updated<br/>(post-commit, failure-armored — a realtime<br/>hiccup never 500s the webhook after the<br/>inbound is durable)
    H->>DB: refresh conversation mode<br/>existing HUMAN → stop before extraction
    H->>DB: capture explicit self-reported name<br/>existing lead upsert; no LLM or queue
    H-->>RT: lead.updated (when captured)

    rect rgb(245, 235, 235)
    Note over H,DB: ── mode policy guard layer 1/4 ──
    H->>H: run_start_guard(conv)<br/>HUMAN / CLOSED → "starved_human_mode"<br/>SEMI_AUTO → wait 30min after human inactive<br/>BOT → allow
    end

    rect rgb(245, 235, 235)
    Note over H,DB: ── mode policy guard layer 2/4 ──
    H->>DB: acquire_lock(conv.id)<br/>atomic bot_locked_until UPDATE<br/>return "locked" if held
    end

    H->>RQ: enqueue_chat_run(job)
    Note over H,RQ: backpressure: max_depth check,<br/>503 + lock release on enqueue fail
    W-->>E: 200 ACK {status: "processing"} (< 1s)
    E-->>Z: 200
    Z-->>U: delivered (inbound)

    Note over WK: ══ bot turn (run_turn, line 259) ══

    RQ->>WK: job
    WK->>Z: tracked typing bridge during dependency setup (bot channel)
    WK->>DB: get conv + refresh
    rect rgb(245, 235, 235)
    Note over WK,DB: ── mode policy guard layer 3/4 ──
    WK->>WK: recheck_ownership(conv, version_at_start, lock_owner)<br/>mismatch → "suppressed" (lock_owner_lost)
    end

    WK->>DB: record_bot_pending → Message BOT PENDING<br/>"Đang soạn trả lời..."
    WK-->>RT: message.created + conversation.updated
    WK->>Z: native typing heartbeat (immediate, then every 3s, bot channel)

    rect rgb(235, 242, 255)
    Note over WK,DB: ── project matching authority ──
    alt generic request for current jobs
        WK->>WK: bypass FAQ/direct-context and route to required list_active_projects
        WK->>DB: load the complete active project catalog
        WK->>WK: return ranked project evidence + presentation contract
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
    Note over WK: ── no canned reply lanes: the agent authors every reply ──
    Note over WK: fast_lane / faq_bypass retired — the only code-authored text<br/>is the two TingTing verbatim strings in _agent_turn
    alt fall through to agent (every turn)
        WK->>WK: build_system_prompt (persona + active recruitment knowledge projects)
        WK->>WK: route_turn → 8 intents, deterministic (no LLM)
        WK->>DB: lead.context(chat_id) → profile + probing question
        WK->>WK: build_agent_user_text (private history + lead + route hint)
        Note over WK,ZS: prefetch tool for high-confidence routes<br/>(search_knowledge / search_bus_timetable)
        WK->>WK: agent.agent() LLM loop (max 6 iterations)<br/>Redis concurrency semaphore,<br/>tool dispatch = WHERE RAG RETRIEVAL HAPPENS<br/>(search_knowledge, list_active_projects, get_product_features...)
        WK->>WK: grounding.validate_entity_grounding + id strip — remove hallucinated job IDs and unsupported entity claims<br/>+ contact guard → one model rewrite round, else suppress
    end
    end

    Note over WK: ── reply boundary ──
    WK->>WK: agent.agent() answer-completion guard<br/>(up to two tool-free continuations, then one concise complete rewrite;<br/>suppress if still capped or empty)
    WK->>WK: _finalize_user_visible_reply<br/>strip_provider_artifacts only — the answer<br/>ships as generated (no rewrite, no truncation)

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
        ZS->>Z: Bot: bot-api.zaloplatforms.com/bot{token}/sendMessage<br/>OA: openapi.zalo.me/v3.0/oa/message/cs<br/>(lossless bounded text chunks)
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

The final reply preserves the complete sanitized model answer; it has no
450-character presentation cutoff. Provider output-cap recovery has a separate
bounded, tool-free allowance even when the normal tool loop used its last round.
If two continuations cannot finish, one final rewrite must produce a complete,
concise answer over the same verified evidence. A capped or empty rewrite is
suppressed and recorded as an answer-completion failure, rather than treated as
a complete project list. An explicit request for all projects instructs the
model to include every project in the current authorized catalog.

Progressive delivery waits for the completed answer on catalog turns. This costs
the early first bubble but prevents a partial list from reaching the candidate
before recovery can finish. Other progressive turns retain their early bubble;
the remainder follows the finalized grounded answer, never a discarded raw
stream tail. Transport splits long text without dropping content, checks channel
authority before each chunk, and treats a failure after an accepted prefix as
an unknown send outcome so recovery cannot replay that prefix automatically.

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
excluded by later webhook bot starts and reconciler recovery. An unassigned
thread is read-only in the console until a recruiter clicks **Tiếp quản**.
Returning it to `BOT` is rejected until it has been claimed; an authorized
release clears the review flag and restores chatbot processing.

**Consultant reply ⇒ SEMI_AUTO (operator rule 2026-09-28).** A consultant's
human reply on a `HUMAN` thread demotes it to `SEMI_AUTO` in the same write
(`recruiter_receipts.record_recruiter_message` / `prepare_recruiter_message`,
with `needs_human` cleared): the thread stays theirs for 30 minutes after the
last consultant message (`_SEMI_AUTO_INACTIVITY`), then `run_start_guard`
admits the bot again on the next inbound — no manual release required.

**Key corrections vs naive "webhook → dedup → normalize → worker → send" sketches**

| Naive sketch | Verified reality |
|---|---|
| `dedup → normalize` | `normalize → dedup` — dedup key is computed during normalize (`webhook.py:111`, `:115`) |
| `verify signature (HMAC)` | Two schemes: Bot = shared-secret compare; OA = SHA256 HMAC (`zalo_oa_signature.py:58`) |
| `apply mode policy` (one step) | Four layers: webhook gate, lock, recheck, atomic `claim_send` (`webhook.py:130`, `:134`, `runner.py:273`, `state.py:329`) |
| `worker: retrieve → generate → policy` | Ten stages incl. two no-LLM fast paths (template + FAQ bypass), routing, lead context, grounding, safety (`runner.py:259-515`) |
| `enqueue → Zalo Send API` | Bot, OA, and recruiter replies first persist one immutable outbox command, then dispatch it. OA commands retain the inbound quote id; a retry reuses the original message and command. |
| (missing) | **First-message resilience (2026-09-28 outage):** a webhook failure AFTER `record_inbound` commits (a realtime serialization `MissingGreenlet` on a just-created conversation) left the message durable but never enqueued; Zalo's redeliveries then hit `uq_messages_conv_provider_message` and 500'd forever. Three guards now close the loop: the conversation create-path eagerly loads `contact`/`channel_identity` for event serialization, `record_inbound` inserts with `ON CONFLICT DO NOTHING` against the partial unique index (a redelivery past the dedup window returns the durable row and re-drives it toward lock+enqueue), and the post-commit event fan-out is failure-armored — a realtime hiccup can no longer turn a persisted message into a 500. |
| (missing) | The outbound dispatcher recovers PENDING commands (~60s). Retryable failures may be explicitly retried from the same recruiter bubble; terminal `SEND_UNKNOWN` is never resent, including a stale SENDING command after a worker crash. |

### 2.4 Candidate source attribution (first touch)

`conversations.attribution` (Alembic 0069, nullable JSONB) records how the
candidate entered. It is written by the inbound path on the first touch that
carries a source and projected read-only as `attribution` on the recruiter
conversation API:

| Encoding | What arrives | Record |
|---|---|---|
| Zalo prefill link `https://zalo.me/<oa>?text=%23<CODE>` | the campaign's post code at the front of the first message (`services/webhook.py::_post_link_attribution`, Bot and OA) | `{"kind": "post_link", "post_code": "BV1026"}` |
| Messenger `message.referral` (Click-to-Messenger ad) | Meta's `ad_id` + `ads_context_data.post_id` / `ad_title` on the first message (`channels/providers/facebook_messenger.py::attribution_from_referral`) | `{"kind": "referral", "post_code", "ad_id", "post_id", "ad_title", "referral_source"}` |
| Messenger `postback.referral` (Get Started / m.me / QR) | our `ref` + `source`, arriving **before** the candidate types — stamped by `webhook_delivery.apply_messenger_referral` because there is no message to carry the write | same shape, usually `post_code` + `referral_source` only |

Meta ships **no `utm_*` parameters** on a Messenger ad: those are appended to
website destinations only, and the `referral` object has no such field (verified
2026-10-06 against Meta's `messages` / `messaging_referrals` webhook
references). `ref` and `ad_title` are the whole campaign signal available here.

Rules: a Zalo code must be the **leading** `#TOKEN`, 2–20 ASCII
alphanumerics/`-`/`_` **with at least one digit** (that rejects `#1`, `#viec`
and every hashtag carrying diacritics), and it is recorded but **never
stripped** — the turn sees the candidate's exact text. First touch wins
(`services/conversation/_shared.py::merge_attribution`): a later touch only
fills keys the record is still missing, which is how the Get Started postback's
`post_code` is completed by the ad's `ad_id`/`post_id` on the first message.
Meta needs the Page subscribed to `messaging_referrals` **and** `messages` to
deliver that ad referral, so `facebook_oauth.subscribe_app_to_page` now sends
`messages,messaging_postbacks,messaging_referrals`; a Page connected before
this change must be disconnected and reconnected once (or re-subscribed from
the App Dashboard) or Meta omits `message.referral` silently.

Zalo OA carries **no** ad/post id in its webhook payload — `user_send_text` is
`{app_id, sender, recipient, event_name, message{text,msg_id}, timestamp}` and
the OA doc corpus has no `ref`/`ad_id`/`post_id`/`campaign_id` (verified
2026-10-06). Per-ad attribution on Zalo therefore comes only from Zalo Ads
**form** leads (`GET openapi.zalo.me/v2.0/oa/form/get` → `adId`, `leadId`), a
separate polling path outside chat.

### 2.5 Project interest — which dự án a candidate is interested in

`lead_events` rows with `event_type = "project_interest"` (no migration — the
payload column already exists) record every project a candidate has engaged
with, once per (lead, project), oldest first, each tagged with the `source`
that found it:

| `source` | Signal | Where it is captured |
|---|---|---|
| `post_link` | the `ref` of a Messenger m.me / Click-to-Messenger ad matched against the project catalog — case-insensitive `projects.slug` or any `projects.aliases` entry — or, when the ad sets no `ref`, the project named by `ads_context_data.ad_title`; stored as `attribution.project_id` | `conversation_messaging/infrastructure/ingress.py` at inbound and `webhook_delivery.apply_messenger_referral` on the postback — both before the candidate types |
| `chat_focus` | the project the conversation's turn focus points at (`conversations.focused_project_id`) | channel-neutral: identical on Zalo and Messenger |

| Seam | When it fires | Why it exists |
|---|---|---|
| `conversation/bot_outcome.py` | after every recorded turn outcome | the conversation trigger (Alembic 0047) creates the lead row together with the conversation, so the signal is attached from the first turn on |
| `candidate_extraction.py` | when the extraction job runs | backstop for a turn whose outcome never ran (crash / reconcile) — idempotent, so it is normally a no-op |

Both call `services/lead/interest.py::record_conversation_project_interest`,
which derives the signals from the conversation, resolves the lead with the
same key rule as extraction (Zalo → `zalo_id`, Messenger → `contact_id`),
skips pairs already recorded, commits in its **own** transaction and swallows
every failure — interest is a hint, never a reason to fail the outcome row or
the extraction job.

The code→project mapping is a **convention**: marketing puts the project slug
in the campaign link — Messenger `https://m.me/<page>?ref=<slug>` (also the
`ref` on a Click-to-Messenger ad's destination) — and the code is matched
case-insensitively. An unmatched code still stores `post_code` (§2.4); it just
resolves to no project. Zalo's link→project resolution is deliberately **not
wired yet** (Messenger first): its capture already exists, so enabling it is
one resolve call in `services/webhook.py`, and a Zalo code must additionally
carry a digit (§2.4), which makes it an *alias* of the project (`lgd26`).

`services/lead/interest.py::resolve_project_from_attribution` is the **single**
cascade both entry paths use, so an ad cannot resolve to one dự án on the
message path and another on the postback path:

1. **`post_code` exact match** — an operator typed it, so it wins outright
   (matched against every project, active or archived: an archived row is the
   record of a project we once recruited for).
2. **`ad_title` substring match** — the fallback for ads already running with
   no custom `ref`. It guesses from free text, so it is held to a higher bar:
   **active projects only**, accent-insensitive and word-anchored via the same
   `normalize_vietnamese_text` + min-2-char rules the in-chat resolver uses
   (`graph/adapters.py`), and an **ambiguous title resolves to nothing** —
   attributing a candidate to the wrong recruiter queue is worse than leaving
   them unattributed, since `chat_focus` can still pin them.

An already-set `project_id` short-circuits, so a re-resolution never replaces
a first touch with a weaker guess.

#### The lead's dự án column

`leads.project_id` (Alembic 0071, nullable FK `projects.id`
`ON DELETE SET NULL`, indexed) carries the same answer as a queryable column,
so lead lists and exports filter by project without an unindexed join over the
JSONB event table. `record_conversation_project_interest` — the same seam that
writes the event — pins it from the **first** signal (link before focus), and
the repository's `WHERE project_id IS NULL` guard makes first-touch hold across
turns, retries and concurrent writers. `version` deliberately does **not**
advance: the recruiter console treats a version bump as a recruiter-visible
edit needing reconciliation, and this is derived attribution nobody typed.

It is read-only (`LeadOut` only, deliberately absent from `LeadUpdate`) and
fully rebuildable from `lead_events`, which is why migration 0071 ships no
backfill.

Read surface: `GET /api/v1/leads/{id}/project-interests` returns the list
(`ProjectInterestOut`) with the project's **current** slug/name resolved live,
so a renamed project never reports a stale name and a deleted one drops out.
The row is also shown in the conversation context panel ("Dự án quan tâm"),
and the raw events are visible on the existing `GET /leads/{id}/events`.

Free-text "muốn ứng tuyển" statements remain candidate extraction's business:
they are recorded in `lead.notes` under its own strict evidence rule
("đang tìm hiểu" ≠ "muốn ứng tuyển") and are deliberately not merged into
`project_interest`.

### 2.6 Lead details extraction — two tiers

A candidate's details are captured by two deliberately different mechanisms,
split by whether the field's vocabulary is **closed** (a pattern wins) or
**open** (only the model can read it):

| Tier | Fields | Where / when |
|---|---|---|
| **Deterministic** (`services/lead/normalizers.py::deterministic_lead_details` + the explicit-name resolver) | name (explicit template, plus a bare reply to the bot's name request), age (`25 tuổi`/`25 tuoi`), birth year (`sn 1998` / `sinh 2001`), expected salary (`12 triệu`, `12-14 triệu`, `12tr5`, `12.000.000` — only when the message also says `lương`/`thu nhập`/`salary`), phone (the typed contact-evidence path, `services/lead/contact_evidence.py`) | **on the inbound path**, one upsert inside `CandidateExtractionService.persist_explicit_details` — Zalo via `services/webhook.py`, Messenger via `conversation_messaging/infrastructure/ingress.py`. No queue, no model, no gate. |
| **LLM** (deferred job on `persistence_low`) | `desired_job`, `living_area`, `address`, `gender`, `years_experience`, notes, contact intent — plus refinement of anything tier 1 found | after the reply is sent (`graph/dispatch.py::_record_dispatched_outcome`); gated by the greeting gate, the conversation mode, and the human-review rule |

Why the split: a regex on an open vocabulary produces wrong values a
recruiter acts on (a name or a district guessed from prose), while a closed
shape produces wrong values only when the message itself is ambiguous — so
salary is keyword-gated and the age/year bounds stay in **one** place
(`normalize_lead`'s 15..80 / 1900..current contract).

Reliability of the deferred tier (`workers/persistence_worker.py`): a failed
extraction job now **re-raises** after logging, so RQ retries it three times
(15 s / 60 s / 300 s) and keeps it in the failed-job registry — the previous
handler swallowed every exception and reported `Job OK`, which is how a model
or queue failure used to drop a candidate's details silently. An enqueue
failure is logged at ERROR with the chat id (the turn itself still succeeds).

### Recruiter-requested review turns

Besides an inbound message and reconcile recovery, a recruiter can ask the bot to
read a conversation from the console (`POST /api/v1/conversations/{id}/bot-reply`).
The turn enters the same pipeline and obeys the same gates, with two differences:

- **No inbound of its own.** The job carries empty `user_text`, so the agent reads
  the conversation history as its input and the prompt is marked as a review turn
  ("no new message") instead of asking the agent to answer a message that does
  not exist.
- **Silence is a valid answer.** The agent may return `NO_REPLY`; the lane turns
  that into a `manual_skip` suppression, so nothing is sent and the outcome row
  separates "the bot chose not to reply" from a failure. The per-conversation
  lock still applies (a second click is refused while a turn runs), progressive
  send is disabled for these turns so nothing can be delivered before the
  decision, and the mode guard still refuses a recruiter-owned thread.

It exists because the pending-inbound nudge cannot reach every stuck thread: a
candidate can be waiting on a real answer after the bot already replied (an
emoji, say), where there is no unanswered inbound left to re-run.

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

### Admin bot-run audit

A `BotRun` row records one reactive turn: conversation, timing and outcome. It carries no
provider-returned reasoning or tool selection — the admin-only decision trace (and its 30-day
retention tick) was removed on 2026-10-02, so nothing about a run's thinking is stored, exposed or
retained. The console's bot-run log screen and its `GET /api/v1/bot_runs` endpoints were retired;
the table itself stays because the performance dashboard reads it for response-time percentiles.

---

## 3. Bot-turn pipeline topology

Documented in `app/graph/runner.py:1-18`; executed in `run_turn` (line 115).
**Note:** the `langgraph` dependency is declared in `requirements` but **no
`StateGraph` / `add_node` is used**. The topology is plain async node
functions composed by hand — "LangGraph-style" in shape only. Document it
honestly as such.

```
load_conversation_state -> typing -> direct_context?
  generic vacancy listing -> required list_active_projects -> complete ranked active project catalog
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
- **Project matching authority:** generic requests such as “đang tuyển gì?” bypass
  FAQ and focused direct-context resolution, so work-seeking turns go straight to
  required `list_active_projects` with the criteria the candidate stated
  (`job_scope`/`location`/`salary_min_vnd`/`company`/`sort_by`/`strict_criteria`; the model composes
  the arguments — nothing forces `top_k` or caps the list). The tool returns EVERY
  active project, ranked by fit against the stated preferences and annotated with
  per-dimension fit notes; salary, location, and job scope are project features
  the candidate must be happy with, never the answer unit. Its presentation
  contract owns the probe-then-introduce behavior: when preferences are missing
  and the candidate did not ask to see everything, the agent asks one compact
  question first; once any preference is stated (or “xem tất cả”), it introduces
  the ranked projects. Preferences are optional: candidates do not have to
  supply role, location, and salary together. The default ranks the complete
  active catalog; explicit hard limits use `strict_criteria` to exclude projects
  whose supplied facts cannot confirm those limits. Matching recognizes project
  names, aliases, and slugs. The discovery card projection intentionally leaves salary,
  shifts, benefits, and follow-up details to the full project page. Specific
  company, location, or role questions use the published recruitment KB as the
  answer source. In direct-context mode, the system first tries to return a
  verbatim `Question:` / `Answer:` block from the assigned KB; a canonical answer
  is only selected when any explicit requested role is supported by that block.
  Otherwise it falls through to the direct-context LLM call over that full KB. For
  vacancy-thread factual follow-ups, the runner combines the prior vacancy query
  with the current question until a newer named topic appears, so salary,
  benefits, and other details stay scoped to the same company evidence.
  `search_knowledge` remains the path for document facts. Any LLM-generated
  user-visible reply from the direct-context or routed RAG/agent lanes passes
  through the graph-level reply boundary
  (`runner._finalize_user_visible_reply`) before persistence/delivery, whose only
  transform is `strip_provider_artifacts` (inline provider thinking and any
  tool-call markup the provider serialized as content) — the answer is otherwise shipped exactly
  as generated. Template replies, FAQ bypass answers, and evidence blocks remain
  verbatim.
  An empty catalog does not block a real answer from published KB evidence for a
  specific vacancy question.
- **Manifest-scoped runtime handoff:** when a manifest policy is active, the
  runner preserves the same scoped `allowed_tools`, `lookup_query`, and the
  vacancy `required_tool` (`list_active_projects`, with `required_tool_args`
  left `None` so the model composes the criteria) while filtering the allowed
  tools against the manifest's tool registry.
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
- **Typing heartbeat:** the tracked worker bridge and graph heartbeat send
  native Zalo Bot `typing` immediately and every three seconds during processing.
  Absolute deadlines prevent provider latency from shifting the cadence; each
  request has at most a one-second budget and requests do not overlap. Legacy
  heartbeat settings above three seconds remain accepted but use the
  three-second cap. Transient failures retry on later pulses. Handoff, answer
  delivery, suppression, terminal errors, and cancellation drain the task
  before continuing. A recruiter reply (fresh or retried) has no turn-long
  window, so `services/chat_status.py` fires the same status once at
  preparation entry — bounded at two seconds and swallowed on any failure, so
  it can never block the send it precedes. Zalo OA has no typing operation in
  its current adapter, and Facebook Messenger has none either; both skip the
  pulse before any config is resolved.
  The [Zalo Bot API](https://bot.zapps.me/docs/apis/sendChatAction/) defines
  this temporary chat status; it creates no candidate message or lead content.
- **Retrieval scope and provenance:** explicit empty project scopes return no
  evidence. Channel-assigned projects are rechecked against the live active
  catalog; detached KBs, superseded categories, inactive projects, and mismatched
  revision/document ownership cannot satisfy a query. Rendered citations carry
  project and category identity. Oversized evidence rows cannot consume the
  complete budget ahead of later ranked hits. Degraded retrieval is not cached
  as confirmed missing knowledge.

---

## 4. RQ queue model (5 queues)

| Queue | Consumer | Job timeout | Backpressure | Purpose |
|---|---|---|---|---|
| `webhook_high` | `worker-chatbot` (×4, priority 1) | 60s (`chat_turn_job_timeout`) | 40 jobs | Live candidate chat turns. |
| `recovery` | `worker-chatbot` (×4, priority 2) | 60s (`chat_turn_job_timeout`) | 40 jobs | Recovered turns re-enqueued by the reconcile sweep; consumed only when `webhook_high` is empty. |
| `persistence_low` | `worker-persistence` (×1) | — | — | One post-SENT LLM extraction for lead fields, memory facts, and contact intent; high-confidence non-candidate/spam/testing results switch future turns to HUMAN. Isolated from the interactive queue. |
| `ingest` | `worker-ingest` | 3600s (`INGEST_JOB_TIMEOUT_SECONDS`) | — | KB digestion / reindex / bus rebuild. |
| `maintenance` | `worker-maintenance` (×1) | — | 20 jobs | Reconcile sweep, outbound dispatch, and email digest ticks. The `followup` queue and its worker were removed. |

- Container entrypoint: `app/workers/run_worker.py` → calls
  `Worker.clean_registries()` on startup (requeues stuck jobs). It preloads the
  graph and lazy LangChain SDK modules in the parent so forked chat jobs inherit
  them copy-on-write instead of paying the import cost per turn.
- Async bridge: `workers/async_runner.py` — one persistent event loop per
  worker process.
- rq-scheduler runs in its own container; the FastAPI lifespan also registers
  unique ticks via `register_unique_tick` (queue `maintenance`):
  `run_reconcile_tick` (60s) and `run_outbound_dispatch_tick` (60s), plus
  email digest as a cron tick. The proactive follow-up tick and the
  `followup` queue were removed; the Google Sheet sync ticks were removed
  with the feature (2026-10-05).

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
own retry policy; persistence is a best-effort schedule;
reconciliation returns a recovery boolean over already-durable state. Realtime
publishes are separate post-commit snapshot events, not durability claims.
These shapes must not be flattened behind one generic job port.

| Boundary | Commit/enqueue/event guarantee |
|---|---|
| Chat turn enqueue | Backpressure-aware boolean; no claim that rejection was accepted |
| Category/version ingestion | Stable receipt; callers can represent indeterminate acceptance |
| Single-page external sync | Optional receipt with operation-owned retry policy |
| Persistence scheduling | Best effort after the owning state transition |
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
messages, outbound commands, bot runs, integration
settings, installation revisions/validations/setup/state, and versioned
knowledge/provenance records. The legacy recruitment adapter continues to own
jobs, leads, lead events/tags, follow-up tasks, and worker/job feature tables.
The agent persona is not among them: it is a code constant in
`backend/app/prompts/vfic_persona.py`.

The dormant generic kernel adds `case_workflow_versions`,
`case_workflow_stages`, `case_workflow_transitions`, `case_tag_definitions`,
`contacts`, `contact_channel_identities`, `cases`, `case_tag_assignments`,
`case_notes`, and `case_followups`. These tables are schema-only after migration:
`0044` inserts no workflow, stage, tag, Contact, Case, customer, template,
persona, credential, or sample row.

### Redis roles (single instance, 7-alpine, AOF on, 256 MB allkeys-lru)
1. RQ broker (5 queues) + scheduler.
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
  files into RAG units + builds per-project catalog cards. Legacy compatibility
  ingestion can fall back to source-grounded units on digest timeout. One-file
  project training records extraction failures and keeps prepared feature
  values private until the complete category batch publishes (see
  `KnowledgePipeline` and `TrainingCategoryBatch`).

---

## 10. RAG retrieval

Knowledge mode is selected at the Project boundary. Each Project owns one
`knowledge_bases` row in either `DIRECT_CONTEXT` or `RAG` mode; the same KB cannot
be shared by another Project.

- `DIRECT_CONTEXT` stores one replacement-only file and makes a tool-free LLM
  call with the complete page plus bounded recent conversation history. The raw
  page and deterministic normalized text stay side by side in the database.
  (The additive Google Sheet sync row and its worker were removed on
  2026-10-05 — migration 0067 dropped the sync-state tables.)
- `RAG` owns twelve `knowledge_categories`. Immutable
  `knowledge_category_revisions` preserve raw category Markdown, normalized payloads, a
  deterministic checksum, and recovery metadata (`processing_token`,
  `lease_expires_at`, `attempt_count`, `quality_result`). Revisions are staged
  and embedded before a transaction stores indexed evidence and advances only that
  category's active pointer. Revision claims are atomic and each revision can
  own only one evidence document.
- Automatic text training retains original bytes and strictly decoded text
  before queuing provider work. The browser's optional brief preview cannot
  limit the categories scanned. Versioned section checkpoints bind extraction
  to the exact source, retain grounded record quotes and resume completed
  sections; every section accounts for all twelve category contracts. Missing
  categories are reported without clearing existing knowledge, and invalid or
  unsupported extraction fails visibly rather than silently becoming plain
  document ingestion. Upload-time category and feature snapshots protect
  independent administrator edits during slow extraction.
  Automatic worker feature extraction also covers bounded source sections and
  persists checkpoints, so a large source cannot hit an unbounded later provider
  request. Conflicting values retain their variants for clarification and do not
  overwrite an existing reliable feature.
- A one-file training source prepares all its proposed categories and features
  durably without publishing them. Categories are Project-scoped and independently
  valid, without Job reference fields or a Jobs-first authoring requirement.
  The final transaction validates each category's contract, switches all proposed
  pointers and evidence, rebuilds applicable projections, publishes features and
  discovery highlights, and marks the source completed together. An intervening
  manual category change or newer source invalidates the batch snapshot. Provider
  I/O never holds the publication locks; failed preparation leaves existing
  published knowledge available. Identical reupload after a manual change creates
  a new intent, while an unchanged provider-failure retry reuses prepared work.
  Legacy-authority Projects retain their live features and highlights during
  shadow training; `requires_cutover` distinguishes prepared completion from
  live publication. Explicit cutover adopts only a matching current source's
  deferred features without overwriting newer independent edits. The rollback
  snapshot also retains exact feature rows when cutover changes them. Feature
  intent comparison excludes untouched empty rows generated by feature-list
  reads. Successful cutover closes obsolete completed deferred feature intents;
  an identical reupload after real feature edits or supersession creates a new
  source intent.
- Category activation is shadow-only until `project.category_authority_started`
  flips during an explicit cutover. Before that flip, retrieval continues to
  read legacy chunks, Jobs, and routes; live category projections are built only at cutover.
- Cutover snapshots the legacy authority, active KB version, category pointers,
  and project-level projection fields. Rollback restores the saved pointers and legacy
  projections even after post-cutover category updates.
- `conversations.project_context_state` and `focused_project_id` select
  `EXPLORE` or one `FOCUSED` Project. Focused tool arguments are server-forced to
  that Project slug; model-supplied cross-Project arguments are ignored.
  Messenger Page assignments also constrain focused direct-context resolution.
  Cached routing entries cannot authorize access: active state, current KB,
  name/aliases, and knowledge mode are refreshed for named or focused targets.
- The cached agent preamble always carries a compact index of every active Project
  (name, slug, aliases, discovery summary, roles, location, and highlights). Current-hiring
  questions never rely on that index or semantic search as matching authority:
  generic lists/counts, named factories, named roles, and terse follow-ups in an
  active vacancy thread all require the complete `list_active_projects`
  catalog for that turn. Full Project knowledge is loaded only for follow-up details.
- Legacy and category-derived Jobs/routes coexist physically and every candidate/recruiter
  consumer gates them with `category_authority_started`. Category-derived Jobs use presence in the current active Jobs revision as availability. Manual status is not an
  authority. A Jobs replacement replays active sibling projections; Transportation
  also replaces Project-scoped `bus_routes` and `bus_stops`.
- Project-wide category scalar facts enter derived role filters only when all
  category records agree; missing or conflicting values become unknown. Full
  source facts remain available to retrieval. Structural `job_ids`, `jobs_ids`,
  `vacancies` and `employment_type` fields from old content are removed at parse, write, read, export and chatbot
  evidence boundaries, including cached evidence. Immutable historical source,
  checksums and recovery checkpoints are preserved rather than rewritten.
  KB roles preserve existing capacity counts; new derived roles have unknown
  capacity rather than an invented vacancy count.
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
  Semantic entries have independent expiry and access-based LRU ordering. Cache
  generations use random signed-64-bit-safe seeds when a counter is missing;
  concurrent initializers adopt the winner. Retrieval captures its generation
  before computation so an old result cannot populate a newly invalidated scope.
  Eligible generated-answer scopes hash private intake context and messaging
  provider; turns with earlier conversation history bypass shared answer reuse.
  Publication repairs knowledge, semantic, Jobs, and preamble namespaces after commit.
- **Pre-publication check:** a bounded sample of declared questions/titles is
  compared with each record's own embedding. Another record's high similarity
  cannot satisfy the check. This is a retrieval sanity check, not proof of factual
  entailment or a guarantee of rank under whole-KB competition.
- **Proactive prefetch:** `_should_prefetch_knowledge` (`clients.py:78`) runs
  KB retrieval before the agent call when the turn looks knowledge-bound.
  Focused FAQ-detail turns may also prefetch `get_product_features` alongside
  `search_knowledge` when an isolated retrieval session factory is available;
  EXPLORE turns remain RAG-only.
- **Tools exposed to agent:** `list_active_projects`, `search_knowledge`,
  `get_product_features`, `search_user_memory`, `search_bus_timetable`.
- **Geo-distance ("dự án nào gần nhà"):** the recruiter's brief is the only
  place a project's verbatim work address lives (`ProjectCreate` shortens it to
  the city before `buildJobsMarkdown`, so `Job.address` /
  `index_card['location']` carry the short value; the brief survives as
  `KnowledgeDocument.raw_text` for `source == 'upload'`). At card-write time
  `refresh_from_kb` (`services/geo/project_address.py`) has the project's LLM
  extract the work address from that brief, grounds it against the same text
  (≥80% of its normalized terms must appear — an LLM-completed address is
  dropped, never stored), and geocodes it onto
  `projects.extracted_address`/`latitude`/`longitude`. `extracted_address` is
  also the cache that keeps a re-ingest from calling the model again; the
  category `jobs` projection and the admin discovery card only geocode their
  human-authored location and defer while the pipeline has not resolved the
  project (no LLM call on either write path). `list_active_projects` geocodes
  the candidate's stated area into an origin, so each payload row carries
  `distance_km` and the default fit order becomes nearest-first (an explicit
  `sort_by` still wins; `origin=None` — a geocoder miss — reproduces the
  previous output exactly, and a project without coordinates carries no
  distance and sorts last). Distance is additive evidence, never a filter.
  Geocoder: two hops, each entered only when the previous one misses —
  **Google** (`GET /maps/api/geocode/json`; measurably the best on the plants
  this bot serves: 0.92 km median error against OSM ground truth vs Vietmap's
  2.74 km), then **Vietmap** (`GET /api/search/v4` → `ref_id` → `GET
  /api/place/v4`; the Vietnam-native provider that resolves the local landmarks
  OSM lacks). There is deliberately **no keyless provider**: Nominatim was
  removed on 2026-10-03 because its relaxation ladder answered a KCN Tràng Duệ
  address with the Hải Phòng city centroid — the wrong "1.5 km" distance — and
  its 1 req/s policy turned a free fallback into a latency floor. Both hops are
  optional and admin-editable (`/admin/integrations/geocoder`;
  `GOOGLE_MAPS_API_KEY` / `VIETMAP_API_KEY` seed the default, a stored value
  wins), and an unconfigured hop is never called, so an installation with
  neither key reports no distance at all. Each hop receives only the caller's
  exact text — a keyed provider answers a partial query with a confident
  *wrong* match rather than nothing, so nothing is ever relaxed — and the
  project bounding box reaches Vietmap as a ranking `focus` point. A factory
  coordinate is stored only when it survives containment: a human-verified
  `geo_gazetteer` row, or a provider point whose Google reverse lookup reports a
  place the address itself names (`geo_gazetteer`, `geocode_place_check`).
  Two cache layers sit in front of both hops: Redis
  (30-day positive / 6-hour negative) over a durable `geocode_cache` mapping that
  records the resolved coordinates *and* which provider won, with a NULL-coordinate
  row per recorded miss so improved coverage is picked up without a backfill.
  Every call is fail-open: a geocoder or model outage degrades to today's
  token-overlap answer and never fails an ingest, a PATCH, or a turn.
  `scripts/backfill_project_coordinates.py` resolves existing projects
  (`--force` re-geocodes, `--re-extract` re-runs the extraction).
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

### 11.2 The employee-support OA (TingTing), a second Zalo OA

See ADR-0013. The recruiting OA stays the seeded `default:zalo_oa` account with
its singleton credentials; the operator's **support** OA for the employee password
reset (ADR-0012) is a second channel account, `zalo_oa / tingting`.

- **Configuring it:** the TingTing settings card holds the same four fields as the
  Zalo OA card (App ID, Secret Key, OA Access Token, OA Refresh Token) plus
  "Lưu & kiểm tra". Saving probes Zalo's `getoa` with the effective access token
  (`app/services/tingting_oa.py`): the response's `oa_id`/`name` are written to
  the account's `provider_metadata`, the account is registered ACTIVE, and the
  binding `tingting_reset_oa_id` is set to `tingting`. There is **no** OA-id or
  account-key field to type. A failed probe still stores what was typed, records a
  redacted `last_error`, leaves the account INACTIVE and the flow off; a cleared
  four-field submission unlinks (credentials destroyed). `POST
  /api/v1/admin/integrations/tingting/oa/check` re-probes the stored values.
- **Storage:** the four credentials live under the standard per-account namespace
  (`zalo_oa_*:tingting`), so `resolve_zalo("tingting")`, the account-scoped refresh
  lock (`zalo:oa:token:refresh:tingting`) and the senders work unchanged.
- **Routing:** `ZaloOaAccountResolver.account_key_for_payload` compares the
  event's OA id (from `ZaloOAWebhookEvent.oa_id`, kind-aware: root `oa_id`, else
  the sender on receipt events, else the recipient) with the registered one →
  `tingting`, otherwise `default:zalo_oa`. Events are never dropped.
- **Serving:** on `tingting` the turn binds only the TingTing reset tools (no
  project knowledge) and the guide. An employee who has not named a problem
  (greeting, "tôi cần hỗ trợ", an unreadable or low-confidence reading) is asked
  which problem they have, on the reset toolset, and keeps the thread with the
  bot; only a confident non-support question is answered with the fixed line
  "Vui lòng chờ chuyên viên tư vấn liên hệ." and flagged for a human. Everywhere
  else an employee-support intent gets the fixed pointer to the support OA
  (`https://zalo.me/3383849659955472174`). Off the support OA the TingTing tools
  are stripped from the registry.
- **Flow binding:** `runner._tingting_reset_allowed` requires provider `zalo_oa`,
  `account_key == "tingting"` and the pin `tingting_reset_oa_id == "tingting"`;
  the original OA, the Bot channel and Messenger can never run it.
- **Admin-only threads:** `viewer_scope.py` adds a correlated `NOT EXISTS` on the
  canonical identity (`support_account_condition` / `support_account_sql`) and the
  lead twin, applied through `viewer_conversation_filter` / `viewer_lead_filter` at
  every conversation and lead read, plus the dashboard's raw-SQL aggregates and
  the realtime socket check. Candidate extraction and inbound name capture
  skip the account. Admins read the threads via the
  `tingting_oa` badge on `/#/conversations`
  (`ChannelAdapterSelector` + `conversation-list-filters.ts`, one extra per-badge
  attention count); the plain `zalo_oa` badge excludes the `tingting` account key,
  so the two OA badges are disjoint in both the list and the reason-scoped page.

---

## 12. Proactive follow-up — REMOVED

The bot no longer initiates contact. The whole proactive path was removed:
`app/workers/followup_worker.py`, `app/services/proactive/`,
`app/recruitment/domain/proactive.py`, `app/graph/proactive.py`, the `followup`
RQ queue, its scheduler tick, the `followup_queue_max_depth` setting, the
`followup_allowed` / `proactive_state` fields on `GraphDeps`, and the
`worker-followup` service. Cadence, per-tick cap, and the 47h Zalo-rule window
are gone with it; nothing is queued and no in-chat follow-up is promised.

What survives is the reactive half:
- Opt-out phrase matching still applies, as policy constant
  `PROACTIVE_OPTOUT_PHRASES` in `recruitment/domain/proactive_policy.py`
  (Vietnamese + English substrings: `dừng`, `ko quan tâm`, `stop`,
  `unsubscribe`, …). It is matched reactively in
  `app/services/conversation/bot_path.py` and sets the
  `conversation.followup_opted_out` column.
- Recruiter follow-up **tasks** are a separate, live feature:
  `FollowUpTask` rows, `/api/v1/leads/{id}/follow-ups`, and the dashboard's
  `FOLLOWUP_TODAY` / `FOLLOWUP_OVERDUE` attention states. A human, not the bot,
  creates them. Lead stage, lead score, and the `followup_count`,
  `last_followup_at`, and `last_followup_attempt_at` columns are unchanged.

Outbound escalation uses the code-authored hotline reply
(`vfic_hotline_reply()` in `app/prompts/vfic_persona.py`) on the gated lane,
which hands off to a human rather than queuing a later turn.

---

## 13. Observability endpoints

| Endpoint | Auth | Returns |
|---|---|---|
| `GET /health` | none | `{"status":"ok","env":...}` |
| `GET /metrics` | none (internal) | RQ queue depths (4 queues), worker count, 7 reconcile canary counters. |
| `GET /health/queue` | none (internal) | Chat-path: queue depth, LLM latency (`_RKEY_INVOKE_MS`), 429s (`_RKEY_429`), fallback count, busy/total workers. |
| `GET /api/v1/admin/performance` | admin | End-to-end response-time p50/p95 plus a bucketed trend (window-scaled), and the candidate-phone conversion rate over the same window. |

### Operator alerts (Web Push)

Two failures are silent by nature — an OA whose refresh token was refused (every
send then fails `Access token has expired` and only a human can re-authorize it)
and a reply the provider refuses twice (a full LLM turn per retry, another
undeliverable bubble for the candidate). Both now push a notification to the
browsers of active admins:

| Piece | Where |
|---|---|
| Handles | `push_subscriptions` (one row per browser: endpoint + `p256dh`/`auth`), managed by `/api/v1/notifications` (VAPID public key, subscribe, unsubscribe, self-test). |
| Delivery | `app/services/push/service.py` — fan-out over `pywebpush` in a worker thread, 404/410 pruning, Redis `SET NX EX` dedupe (6 h per condition) that fails open. |
| Triggers | The refresh refusal in `services/integration_settings/providers/zalo.py`, and the two reconcile branches that give up on an undeliverable reply (`reconcile_worker._alert_stuck_conversation`). |
| Browser | `frontend/public/push-sw.js` (`push` + `notificationclick`) injected into the generated service worker; the bell panel carries the on/off toggle and the self-test. |
| Keys | `VAPID_PRIVATE_KEY` / `VAPID_PUBLIC_KEY`, generated by `scripts/generate_vapid_keys.py` and appended to `.env` by `scripts/prod-env.sh` when missing. Blank keys disable the channel (triggers then only log). |

No external APM (no Sentry/Datadog). Structured JSON logs to stdout with
`request_id` correlation via ContextVar + `RequestIdMiddleware`.
`uvicorn.access` muted to WARNING.

---

## 14. Per-project external API — RETIRED

The per-project external API integration (ADR-0011) was removed when the employee password-reset
flow became the deployment-wide TingTing integration of §14b: its project settings panel, the
`GET`/`PUT`/`POST .../{id}/external-api` routes, `ProjectExternalApiService`, `call_project_api`
(tool schema, registry entry, knowledge-capability grant, decision-trace literal, prefetch
scoping) and its FOCUSED-turn prompt block are all gone. The shared boundary primitives now live
in `app/services/external_api_core.py`, and `projects.external_api` survives only as an unread
nullable column (dropping it would be a destructive migration).

## 14b. TingTing app password reset (deployment-wide, embedded guide)

The employee password-reset flow belongs to the TingTing app, not to a project, so it is its own
deployment-wide integration. See ADR-0012 (which supersedes ADR-0011 for this flow).

- **Storage:** one encrypted `integration_settings` row `tingting_api_key` (AES-GCM). That is the
  *only* thing the admin configures.
- **Admin surface:** `GET`/`PUT /api/v1/admin/integrations/tingting` (admin only, status-only
  response: `{api_key: {configured, preview}, configured, base_url, auth_header}`); an audit row
  `update_tingting_integration_settings` is written on every replace. UI: the TingTing section in
  the settings console (`frontend/src/components/atomic-crm/integrations/presentation/TingtingSection.tsx`).
- **Origin:** `TINGTING_API_BASE_DEFAULT` (`https://tingting.vip`) in
  `app/services/tingting_api.py` — origin only; the `/api/v1` prefix belongs to the guide's paths
  (`/api/v1/integration/...`), so it must not be repeated in the base. A validated
  `Settings.tingting_api_base` override exists for dev/smoke (a bad override falls back to the
  default). Never model-supplied.
- **Prompt:** `runner` appends the embedded `=== API TINGTING: ĐẶT LẠI MẬT KHẨU NHÂN VIÊN ===`
  block (`app/graph/tingting_guide.py`) whenever a usable key is stored — **independent of project
  focus**, since no project is involved. The key never enters the prompt.
- **Tools:** four step tools (`app/graph/tools/tingting_api.py`,
  `app/graph/tools/tingting_identity.py`):
  `verify_tingting_identity(phone, full_name, cccd)` decides the identity match in code
  (diacritics/case/spacing folded on names, `+84` folded on digits, CCCD compared as digits) and
  records the verified phone; the verdict also carries the address form ("anh"/"chị") inferred
  deterministically from the name the employee typed
  (`app/shared/domain/vietnamese_gender.py`) — never from the record, which is the verification
  answer key; `send_tingting_otp(phone)`; `confirm_tingting_otp(phone, code)`;
  `reset_tingting_password(phone)` — it sets the password itself, in the operator's fixed
  format `Vfic@<OTP>` (the 6-digit code the employee just verified, e.g. `Vfic@123980`): readable
  over chat, typeable on a phone, changed after the first login, and never chosen by the
  employee. The app's own generator produced unreadable strings (`PN&&mf6P73x4`); a 400
  rejection of our style falls back to that generator instead of failing the reset. `call_tingting_api(method, path, params)`
  remains for the read-only lookup and refuses every mutating path.
- **Egress boundary:** same as §14 (relative path only, `GET`/`POST`, flat bounded params, 8 s
  timeout, 4 000-char cap, no error body, dedupe + ceiling, one egress site); the read-only
  employee lookup skips the dedupe bucket (ceiling only), so a repeated identity re-read is not
  refused as a duplicate. `call_tingting_api` → `RetrievalRepository.call_tingting_api` →
  `TingtingApiService.invoke`; the `X-API-Key` header is attached server-side.
- **Flow state is server-side** (`TingtingFlowStore`, Redis `tingting:flow:<phone digest>`,
  TTL 15 min, merged per step): the `session_id` and `reset_token` never enter the prompt, so a
  code typed in the next turn is verified against the session the send turn created. A verified
  phone is the gate `send_tingting_otp` reads — identity cannot be skipped.
- **Three-try cap:** a wrong answer spends one of the employee's tries — an unknown phone, a
  submitted name that does not match, or a submitted CCCD that does not match; a pure
  progression ask (record found, everything submitted so far matching) spends nothing. The
  counter lives per conversation (`TingtingVerifyAttemptsStore`, Redis, 24 h sliding TTL,
  scope = the conversation id the lane injects server-side into the tool args — never a
  model-supplied argument). The third failure makes the tool dictate the fixed exhaustion reply
  «Dạ thông tin anh/chị cung cấp chưa hợp lệ nên em chưa xác minh được tài khoản ạ. Vui lòng chờ
  chuyên viên tư vấn liên hệ.», raise `conversations.needs_human` (plain flag write,
  `RetrievalRepository.mark_tingting_verification_exhausted`), and stop asking; a verified match
  clears the counter. **Only a recruiter's human message resets the cap**
  (`RecruiterReceiptsMixin.record_recruiter_message` / `prepare_recruiter_message`). The lane's
  escalation hook fires on any reply that ENDS with the consultant sentence
  (`TINGTING_CONSULTANT_HANDOFF_LINE` in `app/graph/tingting_guide.py`, the single source both
  fixed replies and the tool verdict quote), so the exhaustion reply queues a human exactly like
  the bare handoff line does.
- **Channel scope:** the flow exists **only on the TingTing support OA**
  (`_tingting_reset_allowed`): provider `zalo_oa`, `account_key == "tingting"`, and the pin
  `tingting_reset_oa_id == "tingting"` — a value only a verified link writes (§11.2). The original
  recruitment OA, the Bot channel and Messenger never get the guide and never bind the reset tools;
  an account-support turn there is answered with the fixed pointer to the support OA
  (`https://zalo.me/3383849659955472174`). Any configuration-read error fails closed, and an
  unlinked support OA turns the flow off everywhere.
- **Verification precondition:** a record with no CCCD, or a CCCD equal to its own mobile, cannot
  make the CCCD a distinguishing factor; the tool then requires name + phone only instead of
  deadlocking the employee on a field that can never match.
- **Routing:** on the support OA the `employee_support` intent binds the TingTing reset tools only
  (no project knowledge, no catalog) — a focused RAG turn cannot widen it. An OA turn's system
  prompt is the code-defined TingTing persona (`TINGTING_SUPPORT_PERSONA`, plus the embedded guide
  when the API key is configured), never the recruitment persona, the active-project index or the
  recruiting rules; the code persona states the fixed confirm question and the one-message
  three-field ask verbatim. An employee who has not
  named a problem there (a greeting, "tôi cần hỗ trợ", an unreadable or below-floor reading) is
  re-routed to the same `employee_support` branch with reason `employee_support_clarify` so the bot
  asks the fixed question «Anh/chị cần đặt lại mật khẩu ứng dụng TingTing phải không ạ?» and keeps
  the thread; a **confident non-support** intent is answered
  with "Vui lòng chờ chuyên viên tư vấn liên hệ." and hands the conversation to a human. When the
  model itself ends a reply with that handoff line on the OA, the turn queues a human as well (the
  line promises a consultant, so the queue write follows the suffix — the verification-exhaustion
  reply rides the same hook, not only the routing branch).
  Off the support OA those tools are stripped from the registry. A short follow-up while the assistant's last
  message was mid-flow (`TurnDecisions.recent_account_support`, judged from `bot_last_message`)
  re-routes to `employee_support` with reason `employee_support_continuation`, so "sao rồi" keeps
  the tools and answers with the current step.
- **Contact honesty:** a reply that states a phone number or e-mail absent from the turn's tool
  results and prompt text never ships as-is: the agent is told which channels were invented and
  asked to rewrite without them, and a second violation suppresses the turn (empty reply) instead
  of substituting a code-authored line — so a refusal can never route a candidate to an invented
  hotline, and the model stays the single author of every reply.
