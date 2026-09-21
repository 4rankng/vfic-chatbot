---
type: system
title: Conversation lifecycle, ownership, and delivery state
description: Conversation persistence model, per-conversation DB lock + owner token + TTL, delivery-state machine, recruiter-driven transitions (take_over / release / semi_auto / close / reopen), and the outbound dispatcher tick that recovers stale commands.
tags: [conversation, lifecycle, lock, ownership, delivery-state, takeover, release, semi-auto, outbox]
sources:
  - id: openwiki-source-f1735c06f5f45e7db8851d34
    resource: repo://backend/app/conversation_messaging/application/outbound_recovery.py
  - id: openwiki-source-edadf350dada9b9cb9a8f996
    resource: repo://backend/app/conversation_messaging/domain/delivery.py
  - id: openwiki-source-1cee70e5cc8978eb7ab34cf0
    resource: repo://backend/app/conversation_messaging/domain/ownership.py
  - id: openwiki-source-6dcfc1451bcbf8009d0484a9
    resource: repo://backend/app/core/config.py
  - id: openwiki-source-6201c1a523eb3beb2c1d8be9
    resource: repo://backend/app/graph/runner.py
  - id: openwiki-source-55002f5b1d39cf35fd6d60e2
    resource: repo://backend/app/main.py
  - id: openwiki-source-d8298ce2e49ec758107bef0b
    resource: repo://backend/app/models/conversation.py
  - id: openwiki-source-fc120c8d11676fc7f2a9214a
    resource: repo://backend/app/services/audit_service.py
  - id: openwiki-source-a3df0ea2ca704c3ce1314e34
    resource: repo://backend/app/services/conversation/state.py
  - id: openwiki-source-2fdb3b18938bc915ec6158ea
    resource: repo://backend/app/workers/outbound_dispatch_worker.py
generated: { by: "claude-code", at: "2026-09-08T09:17:45.993Z" }
verified:
  - by: openwiki/0.5.0
    at: 2026-09-21T02:42:43.794Z
---

A conversation is the unit of work between a candidate and a recruiter
(assisted by the bot). The conversation row is the source of truth for
who controls it, who owns the in-flight bot turn (if any), what stage
the most recent outbound message is in, and what state the human-side
recruiter has set on it. Every state change bumps `version` (the
optimistic-lock token) and `conversation_seq` (the strict per-conversation
monotonic counter used for "did A process before B?" debugging).

## Persistence shape

`backend/app/models/conversation.py:Conversation` carries:

- **Identity.** `id` (UUID), `contact_id` (FK `contacts.id`,
  `RESTRICT`), `channel_identity_id` (composite FK to
  `contact_channel_identities`), `zalo_chat_id` (nullable, unique
  when non-null — Messenger rows do not carry one), `zalo_channel`
  (`bot` / `oa`).
- **Mode + status.** `mode: BOT | HUMAN | CLOSED`,
  `status: OPEN | …`. Bot turns only run while `mode == BOT`. A
  recruiter take-over flips to `HUMAN`.
- **Lock.** `bot_locked_until`, `bot_lock_owner` (UUID owner token),
  `bot_lock_heartbeat_at`. The lock TTL is `Settings.bot_lock_ttl_seconds`
  (default 180 s).
- **Bookkeeping.** `needs_human`, `project_context_state`, `focused_project_id`,
  `version`, `conversation_seq`, `taken_over_at`, `assigned_recruiter_id`
  (FK `users.id`, `SET NULL`), `unread_count`.
- **Channel timing.** `last_inbound_at`, `last_outbound_at` — used by the
  Standard Window policy for Messenger and by the proactive follow-up
  cadence.
- **Follow-up state.** `followup_count`, `last_followup_at`,
  `last_followup_attempt_at`, `followup_opted_out` — owned by the
  recruitment domain.

`conversation_seq` is **observability-only**: it increments on every
mutation (inbound, bot outcome, receipt, recruiter action, mode
change), so `Conversation.conversation_seq = N` after the Nth event.
No guard logic consumes it; `version` (which intentionally skips bot
outcomes) is the optimistic-lock token.

## Lock policy

`backend/app/conversation_messaging/domain/ownership.py` is the
pure-policy layer:

- `normalize_lock_owner(lock_owner)` accepts `UUID | str | None` and
  returns `UUID | None`. Used everywhere the lock owner crosses
  process boundaries.
- `lock_owner_matches(current, expected)` returns True when
  `expected` is None (no constraint) or `current == expected` as
  strings. Used by `claim_send` and `recheck_ownership`.
- `lock_still_live(locked_until, now=None)` returns True when
  `locked_until > now`. Naive datetimes are normalized to UTC.

The runner's `recheck_ownership` runs after `conv = await svc.get(...)`
and after `deps.db.refresh(conv)` so it sees the live row. A False
result yields `{"outcome": "suppressed", "reason": "lock_owner_lost"}`
without calling the agent or sending anything.

## Delivery state machine

`backend/app/conversation_messaging/domain/delivery.py` defines
`DeliveryState` and the forward-only `_DELIVERY_RANK`:

| State | Rank | Notes |
|---|---|---|
| `PENDING` | 0 | Outbox row staged; dispatcher tick will pick it up. |
| `SENDING` | 0 | Provider I/O in flight. |
| `SEND_UNKNOWN` | 0 | Ambiguous failure (timeout / reset after request may have reached Zalo). Non-retriable; reconciler keeps the row for audit. |
| `FAILED` | 0 | Definite failure; reconciler may re-enqueue. |
| `SUPPRESSED` | 0 | The pipeline refused to send (ownership, stale authority, etc.). |
| `SENT` | 1 | Provider returned ok. |
| `DELIVERED` | 2 | Provider sent a delivery receipt. |
| `READ` | 3 | Provider sent a read receipt. |

`delivery_rank(status)` and `receipt_advances(current, target)` keep
the policy pure so `validate_grounding` / `validate_entity_grounding`
adjudicate against an authoritative rank. Receipt handlers only update
when `receipt_advances(...)` is True — the machine is **forward-only**
and never regresses.

## Outbound dispatcher tick

`backend/app/workers/outbound_dispatch_worker.py:run_outbound_dispatch_tick`
runs on `Settings.reconcile_interval_seconds` (default every 60 s)
via `register_unique_tick` in `app/main.py` lifespan. It delegates to
`composition.conversation_messaging.run_outbound_recovery`, which:

1. Lists outbox rows in `PENDING` (`pending_ids()`) and in
   `SENDING` past the staleness threshold
   (`stale_sending_ids()`, computed from
   `outbound_dispatch_stale_after_seconds(settings)`).
2. For each `PENDING` row, calls `port.dispatch_pending(outbox_id)` —
   the dispatcher claims and sends. For each `SENDING` row past the
   threshold, calls `port.terminalize_stale_sending(outbox_id)` — the
   reconciler finalizes a stale in-flight command **without
   resending** (the original request may have already reached Zalo).
3. Counts completed / skipped / failed and aggregates a
   `OutboundRecoverySummary`. Failures are isolated per command via
   `on_failure(candidate, exc)` — one broken command cannot stop the
   sweep.

The same composition also runs `_dispatch_pending` directly when the
chat pipeline enqueues an outbox row, so a fresh command typically
does not wait for the next tick.

## Recruiter-driven transitions

`backend/app/services/conversation/state.py` is the mutation surface.
Every transition uses a conditional UPDATE guarded by the
optimistic-lock version so two recruiters racing on the same
unassigned conversation produce exactly one winner and one
`ConversationConflict`.

### take_over

`take_over(conv, recruiter)` atomically:

- Sets `mode = HUMAN`, `status = OPEN`.
- Sets `assigned_recruiter_id = recruiter.id`, stamps `taken_over_at`.
- Clears `needs_human`, `unread_count`, **and the bot lock**
  (`bot_locked_until`, `bot_lock_owner`, `bot_lock_heartbeat_at` all
  set to NULL).
- Bumps `version` and `conversation_seq`.

On success a SYSTEM message is recorded: `"<recruiter full_name> đã
tiếp nhập hội thoại."`, and an audit row tagged
`take_over_conversation` is appended via `record_audit`. A
realtime `conversation_updated` event is published.

### release

`release(conv, actor)` flips the conversation back to BOT mode. A
non-admin actor may only release their own conversations or an
unowned one where `needs_human` is False. This is the "I am done
hand-holding" transition — the bot is back in charge.

### semi_auto

`semi_auto(conv, recruiter)` is the collaborative state: a recruiter
stays assigned but the bot also replies to simple intents.
`_SEMI_AUTO_INACTIVITY = timedelta(minutes=5)` is the staleness bound;
if no recruiter message in 5 minutes, the bot is silenced on
escalation intents. The inbox UI exposes this state visually; the bot
honors it by skipping intents tagged as escalation-only.

### close / reopen

- `close(conv, actor)` sets `mode = CLOSED` (the bot stops replying
  entirely until the conversation is reopened).
- `reopen(conv, actor)` clears `mode = BOT`, `status = OPEN`,
  `taken_over_at = NULL`, `assigned_recruiter_id = NULL` and bumps
  the locks + version. Reopen is a clean reset, not a continuation.

### audit + realtime

Every state mutation funnels through `record_audit` and the
`ConversationEventsPort` (`events.py`) so the recruiter console sees
the change via the realtime bridge (see
[`openwiki/messaging/realtime-socketio.md`](../messaging/realtime-socketio.md))
and the audit table records who did what.

## Recruiter inbox reads

The inbox is delivered through TanStack Query against the conversations
endpoint. `services/conversation/repository.py` is the read surface,
and `services/conversation/scheduler.py` owns the per-recruiter inbox
projection (paged, grouped by SLA bucket, etc.). Recruiter presence is
tracked through `services/presence.py` and surfaced to other recruiters
via the realtime bridge.

## What the recruiter console never does

- **Never sets the bot lock directly.** The lock is owned by the chat
  pipeline; take_over clears it as a side effect, but a recruiter
  cannot inject an arbitrary `bot_lock_owner`.
- **Never decides delivery state.** Provider receipts advance
  `DELIVERED` / `READ`; the runner records `SENT` / `SUPPRESSED` /
  `FAILED` / `SEND_UNKNOWN`. The console renders, never writes.
- **Never bypasses `version`.** Every conditional UPDATE carries the
  optimistic-lock guard so a stale console view cannot clobber a
  newer in-flight state.
