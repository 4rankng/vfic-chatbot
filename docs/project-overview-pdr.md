# Project Overview & Product Development Requirements (PDR)

**Product:** TingHire (formerly Ting Ting / VFIC miniCRM)
**Last updated:** 2026-07-24
**Status:** Production at `bot.tingting.vip` (DigitalOcean, 2 vCPU / ~4 GB RAM)

---

## 1. Product overview

TingHire is a **Vietnamese recruiting chatbot + recruiter console** that uses
**Zalo** (the dominant Vietnamese messaging app) as its sole candidate channel.
A FastAPI service hosts an always-on chatbot that answers candidate questions,
screens them for open roles, books them into a lead pipeline, and nudges cold
candidates to reply. Recruiters watch every conversation in a Vietnamese-only
React Admin console ("miniCRM"), take over when human touch is needed, and
curate the knowledge base (jobs, bus timetables, FAQs, personas) the bot
reasons over.

The product replaces manual Zalo recruiting — where a single recruiter juggles
dozens of threads, forgets to follow up, and answers the same "lương bao
nhiêu?" question hundreds of times — with a 24/7 bot that grounds every reply
in recruiter-curated knowledge and escalates only the conversations that need
a human.

### Core capabilities

| Capability | Description |
|---|---|
| **Inbound chatbot** | Zalo Bot Platform + Official Account webhooks → <1s ack → async turn pipeline → grounded reply. |
| **Bot-turn pipeline** | Agent (MiniMax M2.7) → fast safety filter → LLM safety check (MiniMax M2.5) → pre-send guard → Zalo send. Tools: `search_knowledge`, `search_user_memory`, `search_bus_timetable`. |
| **Lead extraction** | An explicit self-reported name is captured during inbound webhook handling; after each SENT reply, a `persistence_low` job enriches remaining/ambiguous lead fields and memory. |
| **Lead kanban** | Stages, tags, assignee, follow-up tasks, AI-assisted actions, chatops shortcuts from the lead card. |
| **Human inbox** | Realtime Socket.IO push, per-conversation rooms, take-over / release / semi-auto / close / reopen, virtualized thread (`virtua`). |
| **Proactive follow-up** | 6h / 24h / 46h cadence, cap 3, 48h-Zalo-rule-safe (47h margin), Vietnamese opt-out phrase matching. |
| **Knowledge base (RAG)** | Per-project docs ingested into pgvector halfvec HNSW + exact re-rank; versioned, re-indexable. |
| **Direct-context sync** | Single-page projects can be refreshed from one public Google Sheet. The sync requires one exact `gid`, supports manual `Xử lý ngay` and daily auto-sync, renders the current FAQ sheet into deterministic Markdown, and preserves the prior page on failure. |
| **Personas** | Agent voice and follow-up policy — CRUD, activate, import, and optional assignment per messaging adapter. One global default serves every adapter unless that adapter selects another Agent. Projects remain knowledge-only. |
| **Reliability** | Reconcile worker sweeps every 60s, recovers lost turns after worker crash (~3-4 min total recovery). Per-chat DB lock owner + optimistic ownership guard prevent stale-run sends. |
| **Audit** | `bot_runs` resource exposes every bot execution for review. |
| **Admin integrations** | Zalo / MiniMax / OpenRouter credentials managed in admin UI, encrypted at rest. |

---

## 2. Target users & personas

### End users (candidates)

Vietnamese job seekers (typically blue-collar / driver / warehouse roles) who
message a VFIC OA or bot on Zalo asking about jobs, pay, location, schedule,
and how to apply. They expect fast, Vietnamese, human-like replies.

### Console users (recruiters / admins)

| Role | Vietnamese | Who | Scope |
|---|---|---|---|
| `admin` | Quản trị | VFIC tech lead / owner | Full access. Manages users, integration credentials, all projects/personas/knowledge. |
| `recruiter` | Tuyển dụng | VFIC recruiting staff (default role) | Owns conversations, leads, follow-ups, knowledge curation. Cannot manage users or integration secrets. |

> Auth dependency `require_recruiter` is satisfied by `admin` too — admins
> implicitly pass every recruiter gate. `require_admin` returns 403 for
> non-admins. Backend RBAC is enforced per-route; the frontend `<CanAccess>`
> layer mirrors it.

---

## 3. Functional requirements

### FR-1 Zalo ingestion
- **FR-1.1** Accept `POST /webhooks/zalo/chatbot` (Bot Platform) verifying
  `X-Bot-Api-Secret-Token` via `hmac.compare_digest`; refuse blind (503) in
  non-dev when no secret is configured.
- **FR-1.2** Accept `POST /webhooks/zalo/oa` (Official Account) verifying
  `X-Zevent-Signature` as `sha256(appId+data+timestamp+OAsecretKey)`.
- **FR-1.3** Acknowledge every webhook in <1s. Return 503 on enqueue failure
  so Zalo retries the callback.

### FR-2 Bot turn
- **FR-2.1** Per-conversation at-most-one in-flight turn (conversation-row
  lock with owner token, TTL `bot_lock_ttl_seconds` = 180s).
- **FR-2.2** Pipeline topology fixed (see `app/graph/runner.py`); safety nodes
  run before any send; ownership re-checked at `pre_send_guard` so a turn
  started before a recruiter take-over is suppressed after it.
- **FR-2.3** Tool-loop ceiling `max_llm_calls_per_turn` = 6.
- **FR-2.4** On LLM 429: one retry with jitter, then a static Vietnamese
  degradation reply (no off-policy content sent).

### FR-3 Candidate reply delivery
- **FR-3.1** `ZaloChannelSender` dispatches per-conversation by
  `conv.zalo_channel` (`"bot"` → Bot Platform, `"oa"` → Official Account).
- **FR-3.2** Persist every outbound as SENT or SUPPRESSED with reason.

### FR-4 Lead pipeline
- **FR-4.1** Capture an explicit self-reported name during inbound webhook handling.
  Auto-extract remaining/ambiguous lead fields and memory after each SENT reply
  (`persistence_low` queue). `Contact.display_name` remains provider profile
  data: a clearly person-shaped OA display name may satisfy conversational
  personalization without becoming canonical `Lead.name`. Canonical names come
  from an explicit candidate self-introduction or an admin/recruiter correction.
  Deferred extraction must not replace an existing canonical name unless the
  current candidate message explicitly states a new name.
- **FR-4.2** Kanban supports stage PATCH, assign, tag, follow-up tasks,
  chatops actions.
- **FR-4.3** Open `lead_stage` PATCH issue tracked in roadmap (current state
  documented, not fixed here).

### FR-5 Proactive follow-up
- **FR-5.1** Cadence 6h / 24h / 46h, cap 3 per lead, 47h Zalo window.
- **FR-5.2** Substring opt-out matching on Vietnamese + English phrases;
  honored across the next inbound.

### FR-6 Recruiter console
- **FR-6.1** Vietnamese-only UI; locale pinned to `vi`, fallback catalog
  English (raw keys never shown).
- **FR-6.2** Realtime conversation updates via Socket.IO; lazy autoConnect
  (only after login), websocket-first with polling fallback.
- **FR-6.3** Take-over / release / semi-auto / close / reopen, mark-as-read,
  clear conversation history (admin), send human reply.
- **FR-6.4** Admins and recruiters may edit stored candidate profile fields
  from the conversation context panel. The console submits the loaded lead
  version for optimistic concurrency and refreshes after successful or
  conflicting saves.

### FR-7 Knowledge base
- **FR-7.1** Per-project document ingestion → chunked → embedded (3072-dim,
  OpenRouter text-embedding-3-large default, Gemini fallback) → pgvector.
- **FR-7.2** Retrieval: HNSW candidate generation (default 200) → exact
  vector re-rank → return top-k.
- **FR-7.3** Versioned documents; re-index on content change.
- **FR-7.4** Direct-context projects may attach one public Google Sheet sync
  row. The sync resolves one exact `gid` from the pasted URL, accepts the
  current four-column FAQ sheet shape, and updates the page atomically on
  success.
- **FR-7.5** Manual sync and daily auto-sync share the same worker path; if a
  sync fails, the prior direct-context page remains live.

### FR-8 Auth
- **FR-8.1** JWT (HS256) access token 60 min + refresh token 14 days; both
  carry `ver` = user's `token_version`.
- **FR-8.2** Password change bumps `token_version` → all prior tokens rejected
  at the auth gate (revocation without denylist).
- **FR-8.3** Refresh tokens rotated on each `/refresh`.
- **FR-8.4** Rate limits: login 10/60s/IP, forgot-password 5/300s/IP +
  3/900s/email. Password reset OTP TTL 10 min, attempt limit 5.
- **FR-8.5** Bootstrap admin via `scripts.create_admin` (idempotent
  `--only-if-no-admins` guard in prod).

---

## 4. Non-functional requirements

| ID | Category | Requirement |
|---|---|---|
| NFR-1 | Latency | Webhook ack <1s; bot turn completes within `chat_turn_job_timeout` = 60s (RQ kills stuck turns before per-chat lock expires). |
| NFR-2 | Throughput | 3 `worker-chatbot` replicas sustain ~18 turns/min at 10s/turn; recovered turns ride a lower-priority `recovery` queue so they never delay a live turn. Scale replicas if `webhook_high` depth stays >0. |
| NFR-3 | Backpressure | Reject enqueue when `webhook_high` depth reaches `chat_queue_max_depth` = 40 (returns 503 so Zalo retries later). |
| NFR-4 | Reliability | Reconcile sweep every 60s + 120s grace recovers any lost turn after worker crash (~3-4 min total). SETNX non-reentrancy + per-chat lock owner before touching PENDING rows. |
| NFR-5 | Availability | Single small droplet; containers `restart: unless-stopped`. No external APM (no Sentry/Datadog). |
| NFR-6 | Security — secrets | Boot-time safety checks refuse to start outside dev if `JWT_SECRET` is the committed default, if `INTEGRATION_SETTINGS_ENCRYPTION_KEY` is missing, or if CORS contains `*` (credentials enabled). Integration secrets encrypted at rest. |
| NFR-7 | Security — auth | Argon2 password hashing; JWT crypto on worker thread (`asyncio.to_thread`) to avoid event-loop stalls under concurrent login. |
| NFR-8 | Observability | Structured JSON logs to stdout with `request_id` correlation; `/health`, `/metrics` (RQ depths + reconcile counters), `/health/queue` (chat-path LLM latency / 429s / busy workers). |
| NFR-9 | i18n | Frontend Vietnamese-only. |
| NFR-10 | Data durability | PostgreSQL volume (`vfic_pgdata`) is the source of truth. Redis is **not** backed up by design (orphaned-job OOM source; ephemeral broker/cache/pub-sub store). |
| NFR-11 | Cost | 2 vCPU / ~4 GB RAM droplet. Memory ceiling per chatbot worker = 512M. |

---

## 5. Success metrics

| Metric | Target | Source |
|---|---|---|
| Webhook ack p99 | <1s | Caddy access logs / app logs |
| Bot turn p95 | <30s (typical), hard cap 60s | `/health/queue` `_RKEY_INVOKE_MS` |
| LLM 429 rate | <2% of turns | `/health/queue` `_RKEY_429` |
| Lost turns recovered | 100% within ~4 min | reconcile counters in `/metrics` |
| Recruiter take-over → bot suppression | No stale send ever ships | `pre_send_guard` + ownership token |
| RAG groundedness | Measured by `scripts/benchmark_rag.py` golden cases | benchmark script |
| Frontend bundle | Precache ≤5 MiB (PWA) | VitePWA Workbox cap |

---

## 6. Scope boundaries

### In scope
- Zalo Bot Platform + Official Account as the **only** messaging channel.
- Recruiter + admin roles only.
- Single production region (DigitalOcean droplet, `bot.tingting.vip`).
- Vietnamese candidates and Vietnamese-only console UI.

### Out of scope (explicit non-goals)
- Chatwoot, Supabase, or any third-party CRM/auth provider.
- Other messaging channels (SMS, WhatsApp, Facebook, etc.).
- Multi-tenant / multi-org — single VFIC org.
- Public signup — users are admin-provisioned (`signUp` disabled in client).
- Mobile native apps — the console is a responsive web SPA with a mobile
  layout variant only.
- External APM / tracing (Sentry, Datadog, OpenTelemetry) — not wired.

### Open product questions
- **Logout-on-browser-close:** tokens persist in `localStorage` and refresh
  tokens last 14 days, so users stay logged in across browser restarts. If
  session-scoped persistence is desired, that is a product decision (see
  roadmap).
- **OA integration maturity:** the OA path is implemented in the working tree
  but the inbound webhook + send paths are newer than the Bot Platform path
  — verify before relying on it in prod (verify).
