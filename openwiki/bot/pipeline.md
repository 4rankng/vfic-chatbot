---
type: system
title: Bot-turn pipeline (LangGraph runtime)
description: Per-turn pipeline node order (load → typing → agent → safety → pre-send guard → send), how the graph brain depends on Ports and GraphDeps, how factories wire concrete services, and the conversation lock that enforces at-most-one in-flight turn.
tags: [graph, langgraph, ports, runner, factories, bot-run, lock-ttl]
verified:
  - by: openwiki/0.5.0
    at: 2026-09-08T09:17:45.993Z
---

The bot turn is the hot edge of the system. The pipeline mirrors a
LangGraph topology 1:1 in plain Python so every node has a named function,
every dependency is injected, and the safety/ownership branches are
unit-testable with fakes (no API keys needed). Live parity is exercised
through `graph/factories.py` + `graph/clients.py`.

The runtime topology, taken from `backend/app/graph/runner.py`'s
docstring, is:

```text
load_conversation_state -> typing -> agent
  agent (error) -> error_reply
  agent (ok)    -> fast_safety_filter -> needs_llm_safety?
                     no  -> combine_for_presend
                     yes -> llm_safety_check -> safe_to_send?
                               yes -> combine_for_presend
                               no -> retry_rewrite? (attempt<1) -> agent | combine_for_presend
  combine_for_presend -> pre_send_guard -> ownership_ok?
                            yes -> send_message -> log_sent
                            no  -> log_suppressed
```

Each branch returns either a `TurnOutcome` (`sent` / `suppressed` /
`error`) or a synthetic `SendOutcome` consumed by the proactive runner.

## BotRunState — the per-turn payload

`BotRunState` (`backend/app/graph/types.py`) is the dataclass the worker
hands to `run_turn`. It carries every cross-process input:

- `conversation_id`, `version_at_start` (optimistic-concurrency version),
  `user_text`, `user_name`, `reply_to_message_id`.
- `lock_owner` — the owner token attached when the webhook acquired the
  conversation lock; the runner rechecks ownership before sending.
- `received_at_epoch`, `preamble_start_epoch` — wall-clock stamps so
  `webhook_to_pickup_ms` and `preamble_ms` are derivable for the
  performance dashboard.
- `deadline_at_epoch` — combined with `Settings.soft_fallback_remaining`,
  this bounds how long OA profile enrichment may spend before the
  answer budget is consumed.
- `execution_source` (`"direct"` | `"rq"` | `"web_chat"` | proactive)
  — stamps the row for ops triage.
- `trace_id` — propagated from the webhook `request_id`, ends up on the
  `BotRun.trace_id` index so a single query returns every log line for
  one candidate message.
- `runtime_revision_id`, `authority_generation`, `runtime_fingerprint`
  — the runtime authority stamp that lets `runtime_policy` reject
  pre-authority jobs after a clean cutover.

## GraphDeps — the per-turn injection container

`GraphDeps` (`backend/app/graph/types.py`) is the typed injection
container the brain reads from. Each field is a small interface so the
runner can be unit-tested with fakes:

| Field | Type | Purpose |
|---|---|---|
| `db` | `AsyncSession` | The turn's primary session (not safe for concurrent tool calls) |
| `agent` | `AgentModel` | The agent brain (currently `MiniMaxAgent`) |
| `embedder` | `Embedder` | Shared embedder for retrieval |
| `zalo` | provider-neutral sender | Per-turn; refresh-aware |
| `conversation` | `ConversationPort` | state and lifecycle ops |
| `retrieval` | `GraphRetrievalPort` | One-call retrieval adapter |
| `reply_policy` | `ReplyPolicyPort` | Output policy (e.g. deterministic fallback) |
| `lead` | `LeadContextPort` | Lead-profile context for the agent prompt |
| `make_retrieval` | async context manager | Optional factory yielding a fresh `GraphRetrievalPort` on its own DB session — enables **parallel tool dispatch** with isolated sessions |
| `faq_bypass` | `FaqBypassPort` | Deterministic FAQ short-circuit (before the agent node) |
| `followup_allowed` | callable | `(allowed, reason)` gate for proactive follow-ups |
| `persist` | callable | Fire-and-forget candidate extraction after SENT |
| `enrich_oa_profile` | callable | Best-effort OA display-name/avatar enrichment after ownership validation |
| `runtime_policy` | `RuntimePolicyPort` | New manifest-composed runtime authority |
| `direct_context` | `DirectContextPort` | Resolves the active Agent's standalone KB |
| `delivery_statuses` | `DeliveryStatusValuesPort` | Persistence enum translation injected by the messaging composition root |

## Ports — the dependency-injection interfaces

`backend/app/graph/ports.py` declares the Protocols the brain depends on,
intentionally loose-typed (`Any` for domain objects) so the concrete
service can evolve without dragging the contract along:

- `DirectMessageSenderPort.send_message(recipient_id, text, quote_message_id)`
- `DeliveryResultPort`, `LeadContextQueryPort`, `RecommendationQueryPort`,
  `PersonaBodyResolver`, `ProjectKnowledgeQueryPort`
- `SendOutcome` — provider-neutral value result used for synthetic
  outcomes and for the proactive runner's missing-durable-command path.

The composition root in `backend/app/graph/factories.py:build_deps` is
the only place that constructs the concrete services; tests inject fakes
directly into `GraphDeps`.

## Factories — what `build_deps` actually wires

`backend/app/graph/factories.py` defines two layers:

1. **`_build_cached_clients(db)`** — once per (Minimax version × OpenRouter
   version), constructs the LLM clients + embedder. The cache key covers
   only the LLM providers — **not** Zalo — so an OA token rotation does
   not tear down the cached clients.
2. **`build_deps(db, *, session_factory=None)`** — once per turn, re-binds
   the per-turn pieces:

```python
clients = await _build_cached_clients(db)
integration_settings = IntegrationSettingsService(db, settings=get_settings())
zalo_config = await integration_settings.resolve_zalo()       # cached
zalo_sender = ZaloChannelSender(zalo_config, refresh=integration_settings.refresh_oa_access_token)
profile_sender = ZaloOASender(access_token=zalo_config.oa_access_token)
return GraphDeps(
    db=db, agent=MiniMaxAgent(clients.agent_llm, clients.embedder, fast_llm=clients.fast_llm),
    embedder=clients.embedder, zalo=zalo_sender, ...,
)
```

The `_enrich_oa_profile` closure isolates the provider request from the
main turn transaction (it opens its own session via `session_factory`
when available). The parallel-tool-dispatch path is also wired here: each
concurrent tool call gets its own session through `make_retrieval`, so
the shared `db` is never used concurrently.

## Lock — at-most-one in-flight turn

`Settings.bot_lock_ttl_seconds = 180` (env-tunable, default 180 s). The
webhook acquires the conversation row lock with an owner token before
enqueueing the turn; the worker passes `lock_owner` through `BotRunState`
so the runner can re-check ownership before sending.

Three locks interact:

1. **Reactive ownership** — `svc.recheck_ownership(conv,
   version_at_start, lock_owner)` runs after `conv = await svc.get(...)`
   and after `deps.db.refresh(conv)`. A `False` returns
   `{"outcome": "suppressed", "reason": "lock_owner_lost"}` without
   calling the agent or sending anything. This closes the recheck→send
   TOCTOU and the crash-window for stale SENDING rows.
2. **Runtime stamp** — when `state.runtime_revision_id`,
   `authority_generation`, and `runtime_fingerprint` are present, the
   runner calls `deps.runtime_policy.runtime_stamp_is_current(...)`. A
   non-current stamp suppresses the turn with
   `reason="stale_runtime_authority"`; a missing `runtime_policy`
   suppresses with `reason="missing_runtime_policy"`; an inactive policy
   suppresses with `reason="inactive_runtime_policy"`. Pre-authority
   jobs in a manifest-deployed environment are suppressed with
   `reason="missing_runtime_authority"` — a clean cutover never lets old
   jobs inherit today's capabilities.
3. **Claim-send fence** — `svc.claim_send(conv, version_at_start,
   lock_owner, pending_message_id, reply, outbox_channel, outbox_payload)`
   atomically transitions the row PENDING → SENDING. A rowcount of 0
   means the version moved (takeover or newer inbound) and the runner
   suppresses the send.

The RQ job timeout is intentionally set below `bot_lock_ttl_seconds` so
RQ kills a runaway turn before the lock expires; the reconcile sweep
then picks up the row.

## Pipeline nodes in code order

`run_turn` (`backend/app/graph/runner.py:853`) executes roughly:

1. **load conversation state** — `svc.get(uuid.UUID(state.conversation_id))`,
   recheck ownership, runtime stamp.
2. **(OA only) profile enrichment** — strict ceiling
   `min(OA_PROFILE_LOOKUP_TIMEOUT_SECONDS, max(0, deadline_remaining -
   soft_fallback_remaining))` so a slow OA response never pins the
   answer budget.
3. **typing heartbeat** — `_status_heartbeat(zalo, recipient_id)` for
   Zalo Bot and Zalo OA conversations; cancelled before any real send.
4. **last_messages / pending record** — `svc.last_messages(conv,
   limit=RECENT_HISTORY_LIMIT)` and `svc.record_bot_pending(conv,
   **pending_kwargs)` stamp the PENDING row.
5. **route_turn + agent** — `route_turn(state.user_text)` selects the
   intent; the agent builds the prompt, calls tools (retrieval,
   knowledge, FAQ), and produces a candidate.
6. **fast_safety_filter** — deterministic checks against the candidate
   (PII, prompt-injection patterns, recruiter-visible language). Falls
   back to `FALLBACK_REPLY` on hard hits.
7. **llm_safety_check** — only when `fast_safety_filter` flags
   `needs_llm_safety`. The LLM judge may retry/rewrite at most once
   before the candidate is sent.
8. **combine_for_presend** — merges the candidate with persona body and
   delivery metadata.
9. **pre_send_guard (claim_send)** — atomic PENDING → SENDING with
   ownership + version recheck. Suppresses on rowcount 0.
10. **send_message** — `_dispatch_claimed_message` calls
    `zalo.send_message(recipient_id, text, quote_message_id)`.
11. **log_sent / log_suppressed** — `svc.record_bot_outcome(...)` writes
    the final outcome (SENT / SUPPRESSED / FAILED / SEND_UNKNOWN) plus
    `stage_timings` and the optional `decision_trace` JSONB.

## Tracing and timing

A `DecisionTraceBuilder` (`app/graph/decision_trace.py`) is allocated at
the start; `trace_sink.record_decision(...)` is called from the runner
at branch points. The snapshot is taken at claim_send time and stored on
`BotRun.decision_trace`. Per-stage timings are accumulated into
`timings` and persisted via `record_bot_outcome` as
`BotRun.stage_timings` JSONB — used by the performance dashboard.

## Outbound error classification

`_dispatch_claimed_message` returns a `SendOutcome`. The runner
classifies the result:

- `send_result.ok` → record SENT with the bot's reply.
- `send_result.suppressed` → SUPPRESSED.
- `send_result.error_class in AMBIGUOUS_SEND_CLASSES` (timeouts, resets
  after the request may have reached Zalo) → SEND_UNKNOWN
  (non-retriable, reconciler keeps the row for audit).
- any other failure → FAILED (reconciler may re-enqueue).

`AMBIGUOUS_SEND_CLASSES` lives in `app/shared/application/outbound.py`,
shared with the outbound dispatcher that runs on the periodic tick.

## Tests and fakes

The runner is the public contract for unit tests; `GraphDeps` accepts
fakes for every port. The test suite
(`backend/tests/test_concurrency.py`, `test_conversation_history_clear.py`,
etc.) drives `run_turn` end-to-end without API keys, using the
`tests/integration` lane only where a real PostgreSQL+pgvector is
required.
