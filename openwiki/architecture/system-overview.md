---
type: architecture
title: System overview and component topology
description: How the synchronous answer path, background workers, edge, and realtime push fit together — and which subsystem owns each step of an inbound Zalo message.
tags: [architecture, fastapi, rq, redis, postgres, pgvector, socketio, lifespan]
verified:
  - by: openwiki/0.5.0
    at: 2026-09-08T09:17:45.993Z
---

TingHire (formerly Ting Ting / VFIC) is a Vietnamese recruiting chatbot and
recruiter console. The runtime shape is a single FastAPI web tier backed by
RQ workers, with Postgres+pgvector for durable state and embeddings, Redis
for the RQ broker, pub/sub, rate limits, LLM semaphore, and process-local
caching, and a Caddy edge that terminates TLS and routes four upstream
buckets (webhooks, `/api`, `/realtime`, `/socket.io`) to the active blue or
green web color.

The full component diagram lives in
[`docs/system-architecture.md`](../docs/system-architecture.md); this page
focuses on **how the pieces interact per inbound message** and on the
subsystem ownership that emerges.

## Synchronous answer path (Zalo Bot Platform inbound)

```text
candidate → Zalo Bot API → POST /webhooks/zalo/chatbot (Caddy)
  → FastAPI route in backend/app/api/webhooks.py
  → ZaloWebhookService.handle (services/webhook.py)
      → commit inbound message + acquire conversation DB lock + owner token
      → enqueue_chat_turn(job) (composition/conversation_messaging.py)
          → workers.chatbot_worker.enqueue_chat_run
              → enqueue_job("webhook_high", run_chat_turn_job)
  → return <1s ack to Zalo
  → worker-chatbot (×2) dequeues → run_turn via graph.runner
      → build_deps (graph.factories) resolves Zalo + LLM clients
      → load_conversation_state → typing → agent → fast_safety_filter
          → llm_safety_check → pre_send_guard → send_message (Zalo OA)
      → log_sent → enqueue_persist_candidate(persistence_low)
      → release lock
  → recruiter console sees the new message + bot run via Socket.IO
      (backend/app/realtime/socketio.py + bridge)
```

Two facts about this path matter:

1. The web process **does not run the agent**. The webhook commits the
   inbound message, acquires the per-conversation DB lock with an owner
   token, enqueues a job on the `webhook_high` queue, and returns the
   sub-second ack Zalo expects. The LLM-bound work runs on
   `worker-chatbot`, isolated from the user-facing request path.
2. The bot turn itself is a graph topology mirrored 1:1 in code (see
   `backend/app/graph/runner.py`'s docstring). The synchronous answer
   path is the hot edge; every other path is background.

The path for **Zalo OA** webhooks (`POST /webhooks/zalo/oa`) is the same
shape with a different signature scheme. **Facebook Messenger** webhooks
follow the same composition pattern via the channels/ registry.

## Background paths

The other queues exist to keep latency, ordering, and isolation correct.

| Queue | Worker | Purpose | Why isolated |
|---|---|---|---|
| `webhook_high` | `worker-chatbot` ×2 | Interactive bot turns | Two replicas absorb a webhook burst; one slow turn does not block the other |
| `persistence_low` | `worker-persistence` ×1 | Lead enrichment + memory after a SENT reply | Best-effort; must never delay a candidate reply |
| `ingest` | `worker-ingest` ×1 | Knowledge ingest, embedding, re-embedding | Slow; isolated so an upload cannot back-pressure chat |
| `followup` | `worker-followup` ×1 + `scheduler` ×1 | Proactive follow-up + periodic ticks | Single replica; rq-scheduler fires the ticks |

The lifespan handler in `backend/app/main.py` registers every periodic tick
through `register_unique_tick` (or `register_unique_cron_tick` for the
external-source sync) so exactly one recurring job exists per tick. An
earlier version used random job ids and ended up with ~12x duplicate
ticks; the unique-tick guarantee closes that loophole.

| Tick | Interval | Source |
|---|---|---|
| Proactive follow-up | `PROACTIVE_TICK_INTERVAL_SECONDS` (1800 s default) | `recruitment/domain/proactive_policy.py` |
| Reconcile sweep | `settings.reconcile_interval_seconds` | `core/config.py` |
| Outbound dispatcher | `settings.reconcile_interval_seconds` | `core/config.py` |
| Decision trace retention | `settings.decision_trace_retention_interval_seconds` | `core/config.py` |
| External source sync | cron `settings.kb_sync_cron` | `core/config.py` |
| Single-page external source sync | cron `settings.kb_sync_cron` | `core/config.py` |

Each `try` block around a registration logs `non-fatal`; a failure to
register the follow-up tick must not block the web process from starting.

## Subsystem ownership

The system deliberately splits concerns so each subsystem can be reasoned
about, tested, and re-deployed independently.

| Subsystem | Owns | Where |
|---|---|---|
| Edge | TLS, gzip/zstd, security headers, blue/green routing, `/health` probe | `backend/Caddyfile.template`, `backend/scripts/flip_caddy.sh` |
| HTTP API | REST routes + auth gates + installation gate + admin endpoints | `backend/app/api/`, `backend/app/api/auth_dependencies.py` |
| Web ingress | Zalo / OA / Messenger signature verification, DB lock, enqueue | `backend/app/api/webhooks.py`, `backend/app/services/webhook.py`, `backend/app/composition/conversation_messaging.py` |
| Graph | Per-turn pipeline (state load → agent → safety → send) | `backend/app/graph/` |
| Workers | RQ queues, periodic ticks, reconcile sweep, direct-turn drain | `backend/app/workers/` |
| Realtime | Socket.IO server, cross-process bridge, per-conversation rooms | `backend/app/realtime/` |
| Persistence | SQLAlchemy 2.x models, Alembic hand-written migrations | `backend/app/models/`, `backend/alembic/` |
| Knowledge | Canonical knowledge format, embedding, pgvector retrieval | `backend/app/project_knowledge/` |
| Recruitment | Lead lifecycle, candidate extraction, proactive policy, recommendation | `backend/app/recruitment/` |
| Capabilities | Code-reviewed capability registry and parity artifact | `backend/app/capabilities/` |
| Access | Role policies + installation access | `backend/app/access/` |
| Identity | Auth service, password reset, JWT | `backend/app/identity/` |
| Console | React Admin SPA on `atomic-crm` template | `frontend/src/` |

## The four data flows

### 1. Chat turn (synchronous)

Owned by the graph layer. `graph/runner.py` carries the topology in its
docstring: `load_conversation_state → typing → agent → fast_safety_filter →
needs_llm_safety? → (yes → llm_safety_check → safe_to_send? → retry_rewrite?)
→ combine_for_presend → pre_send_guard → ownership_ok? → send_message →
log_sent`. Ports in `graph/ports.py` declare what the brain calls;
`graph/factories.build_deps` wires the concrete services. The
`_run_persistence_low` callback (`chatbot_worker._enqueue_persist`) is the
only side-channel that crosses out of the graph layer during a turn.

### 2. Realtime push

`backend/app/realtime/socketio.py` mounts the Socket.IO ASGI app on the
web process and joins each authenticated recruiter to per-conversation
rooms (`conv:<id>`). Because workers and web are separate processes, the
publish side goes through a **cross-process emit bridge** in
`realtime/emitter.py` so a turn that finishes in `worker-chatbot` still
appears on the recruiter's console without polling. The legacy SSE
firehose (`/realtime/*`) is kept as a fallback; Caddy uses
`flush_interval -1` so events flush immediately.

### 3. Proactive follow-up

Owned by the recruitment domain. `proactive_policy.py` defines a
`FollowupRulesPolicy` with score-specific rules (`hot`, `warm`,
`not_interested`), each carrying a cadence tuple and an eligible-stages
list. The proactive tick enqueues follow-up turns; the conversation
ownership lock from the chat path prevents a proactive turn from racing a
human reply.

### 4. Knowledge refresh

Two paths share the `external_source_sync` worker family:

- **External source sync** (`external_source_sync_worker.py`) — runs on
  `kb_sync_cron` and pulls configured knowledge bases.
- **Single-page external source sync**
  (`single_page_external_source_sync_worker.py`) — also runs on
  `kb_sync_cron`. Each invocation is bound to one project + one exact
  Google Sheet `gid`, renders the current FAQ sheet into deterministic
  Markdown, and preserves the prior page on failure. The state is owned
  by the `external_source_sync_state` model (migration 0053).

Both paths feed the `ingest` worker, which embeds and writes to
pgvector; the retrieval layer then re-ranks.

## Reliability properties

- **Sub-second ack to Zalo.** Webhooks commit inbound + enqueue + return
  in <1s; Zalo's retry contract is honored by returning 503 on enqueue
  failure.
- **One in-flight turn per conversation.** The DB lock with owner token
  + TTL (`bot_lock_ttl_seconds`, 180 s) prevents two turns from replying
  to the same message. The pre_send_guard refuses to send if the lock
  has lapsed.
- **Reconcile sweep every 60s.** Any turn that was committed-but-not-
  delivered (worker crash, network partition) is re-enqueued on the next
  reconcile tick. End-to-end recovery is ~3-4 minutes.
- **Graceful shutdown.** `_shutdown_web_resources` in
  `backend/app/main.py` drains direct turns (5 s), disposes the DB
  engine, closes LLM client bundles, and closes HTTP clients — each
  independent so one close failure cannot strand another pool.

## Observability seams

- `setup_logging()` in `backend/app/core/logging.py` installs structured
  logging and a request-id context that propagates across worker
  boundaries.
- Every bot execution accumulates a `DecisionTrace`; the trace is
  persisted on send or suppression and is visible to recruiters through
  the `bot_runs` resource.
- The decision-trace retention tick prunes the table on
  `decision_trace_retention_interval_seconds`.

## Why this shape on 2 vCPU / 4 GB

The HLD in `docs/HLD.md` frames the design as a **bounded retrieval-and-
ranking system** rather than a broad autonomous agent. The constraints:

- A 2 vCPU / 4 GB droplet cannot host heavy parallel inference; we cap
  concurrent LLM calls with a Redis-backed semaphore
  (`app/graph/llm_semaphore.py`) and shed load with a static Vietnamese
  degradation message (`DEGRADATION_REPLY`) when throttled.
- Webhooks ack fast and let `RQ` carry the LLM-bound work; this matches
  Redis job-queue guidance to keep heavy work off user-facing paths.
- The chat path stays on `webhook_high`; everything slow sits behind a
  different queue, so a slow persistence or ingest job cannot delay a
  candidate reply.

## Where to read next

- **One bot turn in detail** — see
  [`openwiki/bot/pipeline.md`](../bot/pipeline.md) and
  [`openwiki/bot/safety-and-routing.md`](../bot/safety-and-routing.md).
- **Worker layout and recovery** — see
  [`openwiki/workers/pipeline-and-recovery.md`](../workers/pipeline-and-recovery.md).
- **Realtime bridge** — see
  [`openwiki/messaging/realtime-socketio.md`](../messaging/realtime-socketio.md).
- **Deploy / blue-green** — see
  [`openwiki/architecture/deployment.md`](../architecture/deployment.md).
