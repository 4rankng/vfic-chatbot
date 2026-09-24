"""Outbound transactional outbox service (Tech-Lead Directive §14).

Records the dispatch intent for every outbound BOT message in the same DB
transaction as the message write. The outbox row is the authoritative
"was this sent?" record:

- Reconcile reads it to detect duplicates (the duplicate_outbound_rate SLO finally
  has a data source).
- The dispatcher sends PENDING rows and terminalizes stale SENDING rows as
  SEND_UNKNOWN; neither stale SENDING nor SEND_UNKNOWN is ever resent because
  the provider may already have accepted the command.
- A unique constraint on message_id prevents double-enqueue.

The runtime writes ``PENDING`` before every provider call, atomically claims it
as ``SENDING``, then finalizes the same message/outbox pair.  A process crash
leaves either PENDING (safe to dispatch later) or SENDING (terminally
SEND_UNKNOWN; retrying could duplicate a candidate-visible message).

This module is the public facade: the row lifecycle lives in
:mod:`app.services.outbox.repository` and the provider dispatch — the only part
that talks to providers — in :mod:`app.services.outbox.dispatcher`. Both are
re-exported here unchanged so every existing import keeps working.
"""

from __future__ import annotations

from app.services.outbox.dispatcher import (
    _dispatch_claimed_command,
    _dispatch_facebook,
    _provider_for_outbox_channel,
    _refresh_oa_access_token_for_dispatch,
    _resolve_runtime_authority,
    _suppressed_dispatch_result,
    _try_neutral_dispatch,
    dispatch_outbox,
)
from app.services.outbox.repository import (
    DispatchCandidate,
    DispatchResult,
    build_outbox_payload,
    claim_pending_outbox,
    claim_stale_sending,
    claim_stale_sending_unknown,
    count_by_status,
    create_pending_outbox,
    dispatch_message_outbox,
    enqueue_outbox,
    mark_status,
    outbound_dispatch_stale_after_seconds,
    pending_outbox_ids,
    stale_sending_outbox_ids,
)

__all__ = [
    "DispatchCandidate",
    "DispatchResult",
    "_dispatch_claimed_command",
    "_dispatch_facebook",
    "_provider_for_outbox_channel",
    "_refresh_oa_access_token_for_dispatch",
    "_resolve_runtime_authority",
    "_suppressed_dispatch_result",
    "_try_neutral_dispatch",
    "build_outbox_payload",
    "claim_pending_outbox",
    "claim_stale_sending",
    "claim_stale_sending_unknown",
    "count_by_status",
    "create_pending_outbox",
    "dispatch_message_outbox",
    "dispatch_outbox",
    "enqueue_outbox",
    "mark_status",
    "outbound_dispatch_stale_after_seconds",
    "pending_outbox_ids",
    "stale_sending_outbox_ids",
]
