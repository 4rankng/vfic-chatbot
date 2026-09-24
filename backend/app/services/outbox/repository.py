"""Row lifecycle of the outbound transactional outbox (Tech-Lead Directive §14).

Owns the durable ``outbound_outbox`` row and nothing else: the dispatch value
objects, the insert/upsert, the atomic PENDING claim, the sweeps that select and
terminalize stale rows, and the status projections. No provider I/O happens
here — every send goes through :mod:`app.services.outbox.dispatcher`.

The outbox row is the authoritative "was this sent?" record:

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
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.outbox import OutboxStatus, OutboundOutbox
from app.shared.application.outbound import OutboundTelemetry

logger = logging.getLogger(__name__)

# Recruiter messages are capped at 4,000 characters. Because the 420-character
# splitter preserves paragraph/sentence boundaries, an adversarial valid body can
# produce up to twenty short chunks rather than the ideal ten full chunks. OA may
# add one token refresh and one retry. One chat-turn timeout remains as margin.
_MAX_PROVIDER_WINDOWS_PER_OUTBOX = 22


@dataclass(frozen=True)
class DispatchCandidate:
    """A row claimed by the dispatcher sweep for re-dispatch."""

    outbox_id: int
    message_id: int
    channel: str
    payload: dict[str, Any]


@dataclass(frozen=True)
class DispatchResult:
    """One provider attempt for an already-persisted outbound command."""

    outbox_id: int
    message_id: int
    ok: bool
    zalo_message_id: str | None = None
    # Canonical neutral message id (Alembic 0047). When only the neutral path
    # is used, this carries the value; legacy callers read ``msg_id`` below.
    provider_message_id: str | None = None
    error: str | None = None
    error_class: str | None = None
    suppressed: bool = False
    telemetry: OutboundTelemetry | None = None

    @property
    def msg_id(self) -> str | None:
        """Match the sender result contract consumed by the graph pipeline."""
        return self.provider_message_id or self.zalo_message_id


def outbound_dispatch_stale_after_seconds(settings) -> int:
    """Return a recovery age that cannot overtake a bounded live provider send."""

    provider_budget = (
        _MAX_PROVIDER_WINDOWS_PER_OUTBOX * settings.zalo_bot_request_timeout
    )
    return int(provider_budget + settings.chat_turn_job_timeout)


def build_outbox_payload(
    chat_id: str, text: str, quote_message_id: str | None = None
) -> dict[str, str]:
    """Create the immutable provider payload stored with an outbound command."""
    payload = {"chat_id": chat_id, "text": text}
    if quote_message_id:
        payload["quote_message_id"] = quote_message_id
    return payload


async def _active_messenger_generation(db: AsyncSession, channel: str) -> int | None:
    """Capture the single active Messenger Page authority for a new command."""
    from app.channels import types as ct

    if channel != ct.PROVIDER_FACEBOOK_MESSENGER:
        return None

    from app.channels.accounts import ChannelAccountStatus
    from app.models.channel_account import ChannelAccount

    generation = await db.scalar(
        select(ChannelAccount.generation).where(
            ChannelAccount.provider == ct.PROVIDER_FACEBOOK_MESSENGER,
            ChannelAccount.status == ChannelAccountStatus.ACTIVE,
        )
    )
    return int(generation) if generation is not None else None


async def create_pending_outbox(
    db: AsyncSession,
    *,
    message_id: int,
    channel: str,
    payload: dict[str, Any],
    runtime_revision_id=None,
    authority_generation: int | None = None,
    runtime_fingerprint: str | None = None,
    origin_kind: str | None = None,
    fence_scope: str | None = None,
    status: OutboxStatus = OutboxStatus.PENDING,
) -> OutboundOutbox:
    """Persist a command before provider I/O in the caller's transaction.

    Unlike the legacy outcome recorder this deliberately does not swallow an
    insert error: acknowledging a reply without its durable command would make
    crash recovery impossible.

    ``status`` defaults to PENDING (the dispatcher-claimable state). The inline
    bot turn passes SENDING: it writes the command in the same transaction that
    claims the message (``bot_path.claim_send``), so the row is already claimed
    by the time it commits and no dispatcher tick can pick up a row whose inline
    send is still running (REL-06).
    """
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    now = datetime.now(timezone.utc)
    channel_account_generation = await _active_messenger_generation(db, channel)
    stmt = (
        pg_insert(OutboundOutbox)
        .values(
            message_id=message_id,
            channel=channel,
            payload=payload,
            status=status.value,
            # A row written already-SENDING carries the attempt its claim
            # transaction is about to make, the same count
            # ``claim_pending_outbox`` stamps on the dispatcher path.
            attempts=1 if status is OutboxStatus.SENDING else 0,
            channel_account_generation=channel_account_generation,
            runtime_revision_id=runtime_revision_id,
            authority_generation=authority_generation,
            runtime_fingerprint=runtime_fingerprint,
            origin_kind=origin_kind,
            fence_scope=fence_scope,
            updated_at=now,
        )
        .on_conflict_do_nothing(index_elements=["message_id"])
        .returning(OutboundOutbox)
    )
    row = (await db.execute(stmt)).scalar_one_or_none()
    if row is not None:
        return row
    existing = await db.scalar(
        select(OutboundOutbox).where(OutboundOutbox.message_id == message_id)
    )
    if existing is None:
        raise RuntimeError(f"failed to persist outbound command for message {message_id}")
    return existing


async def claim_pending_outbox(db: AsyncSession, *, outbox_id: int) -> DispatchCandidate | None:
    """Atomically claim a single PENDING command for one provider attempt."""
    now = datetime.now(timezone.utc)
    stmt = (
        update(OutboundOutbox)
        .where(
            OutboundOutbox.id == outbox_id,
            OutboundOutbox.status == OutboxStatus.PENDING.value,
        )
        .values(
            status=OutboxStatus.SENDING.value,
            attempts=OutboundOutbox.attempts + 1,
            updated_at=now,
        )
        .returning(
            OutboundOutbox.id,
            OutboundOutbox.message_id,
            OutboundOutbox.channel,
            OutboundOutbox.payload,
        )
    )
    row = (await db.execute(stmt)).one_or_none()
    if row is None:
        return None
    return DispatchCandidate(
        outbox_id=row.id,
        message_id=row.message_id,
        channel=row.channel,
        payload=row.payload if isinstance(row.payload, dict) else {},
    )


async def dispatch_message_outbox(db: AsyncSession, *, message_id: int) -> DispatchResult | None:
    """Dispatch the single durable command belonging to ``message_id``.

    A PENDING row is claimed atomically here (the dispatcher path). A row that is
    already SENDING while its message is SENDING too was claimed by *this*
    caller's own claim transaction — ``bot_path.claim_send`` writes the command
    already-SENDING so no dispatcher tick can pick up a row whose inline send is
    still running (REL-06) — so it is resumed instead of re-claimed. Every other
    status is not ours to send: ``claim_pending_outbox`` remains the only way a
    row becomes sendable, so a command a concurrent sender owns is never sent
    twice.
    """
    from app.services.outbox.dispatcher import dispatch_outbox

    outbox = await db.scalar(
        select(OutboundOutbox)
        .where(OutboundOutbox.message_id == message_id)
        # The status decides whether this caller may send, so read it from the
        # row rather than from a possibly stale identity-mapped instance.
        .execution_options(populate_existing=True)
    )
    if outbox is None:
        return None
    if outbox.status == OutboxStatus.SENDING.value:
        return await _resume_claimed_outbox(db, outbox)
    if outbox.status != OutboxStatus.PENDING.value:
        return None
    return await dispatch_outbox(db, outbox_id=int(outbox.id))


async def _resume_claimed_outbox(
    db: AsyncSession, outbox: OutboundOutbox
) -> DispatchResult | None:
    """Send a command this caller's own claim transaction already marked SENDING.

    Ownership proof: ``claim_send`` flips the message to SENDING in the same
    statement that claims its command, so the message is SENDING as well. A row
    claimed by another sender (the dispatcher sweep claims the outbox alone and
    leaves the message PENDING) belongs to that sender and is never sent from
    here.
    """
    from app.models.conversation import DeliveryStatus, Message
    from app.services.outbox.dispatcher import (
        _dispatch_claimed_command,
        _resolve_runtime_authority,
        _suppressed_dispatch_result,
    )

    # Read the status from the row itself: ``claim_send`` flips it with a raw
    # UPDATE, so an identity-mapped Message instance in this session still holds
    # the pre-claim PENDING value.
    claimed_status = await db.scalar(
        select(Message.delivery_status).where(Message.id == outbox.message_id)
    )
    if claimed_status != DeliveryStatus.SENDING:
        return None
    candidate = DispatchCandidate(
        outbox_id=int(outbox.id),
        message_id=int(outbox.message_id),
        channel=outbox.channel,
        payload=outbox.payload if isinstance(outbox.payload, dict) else {},
    )
    authority, authority_is_current = await _resolve_runtime_authority(db, outbox)
    if not authority_is_current:
        return _suppressed_dispatch_result(candidate)
    return await _dispatch_claimed_command(
        db, outbox=outbox, candidate=candidate, authority=authority
    )


async def pending_outbox_ids(db: AsyncSession, *, limit: int = 25) -> list[int]:
    """Return a bounded oldest-first batch for the dispatcher sweep."""
    rows = (
        await db.scalars(
            select(OutboundOutbox.id)
            .where(OutboundOutbox.status == OutboxStatus.PENDING.value)
            .order_by(OutboundOutbox.created_at)
            .limit(limit)
        )
    ).all()
    return [int(row) for row in rows]


async def stale_sending_outbox_ids(
    db: AsyncSession, *, stale_after_seconds: int, limit: int = 25
) -> list[int]:
    """Return commands whose provider attempt ended without a persisted receipt.

    They are terminally marked ``SEND_UNKNOWN`` by the dispatcher rather than
    retried, because Zalo may already have accepted the original request.
    """
    threshold = datetime.now(timezone.utc) - timedelta(seconds=stale_after_seconds)
    rows = (
        await db.scalars(
            select(OutboundOutbox.id)
            .where(
                OutboundOutbox.status == OutboxStatus.SENDING.value,
                OutboundOutbox.updated_at < threshold,
            )
            .order_by(OutboundOutbox.updated_at)
            .limit(limit)
        )
    ).all()
    return [int(row) for row in rows]


async def claim_stale_sending_unknown(
    db: AsyncSession, *, outbox_id: int, stale_after_seconds: int
) -> DispatchCandidate | None:
    """Atomically terminalize one still-stale command as ``SEND_UNKNOWN``.

    The ID list used by a sweep is only a snapshot.  This conditional update is
    therefore required before finalization: a live worker may have persisted
    ``SENT`` after the snapshot, and the stale sweep must never overwrite it.
    """
    threshold = datetime.now(timezone.utc) - timedelta(seconds=stale_after_seconds)
    row = (
        await db.execute(
            update(OutboundOutbox)
            .where(
                OutboundOutbox.id == outbox_id,
                OutboundOutbox.status == OutboxStatus.SENDING.value,
                OutboundOutbox.updated_at < threshold,
            )
            .values(
                status=OutboxStatus.SEND_UNKNOWN.value,
                updated_at=datetime.now(timezone.utc),
                last_error="outbound dispatch interrupted before receipt",
            )
            .returning(
                OutboundOutbox.id,
                OutboundOutbox.message_id,
                OutboundOutbox.channel,
                OutboundOutbox.payload,
            )
        )
    ).one_or_none()
    if row is None:
        return None
    return DispatchCandidate(
        outbox_id=row.id,
        message_id=row.message_id,
        channel=row.channel,
        payload=row.payload if isinstance(row.payload, dict) else {},
    )


async def enqueue_outbox(
    db: AsyncSession,
    *,
    message_id: int,
    channel: str,
    payload: dict[str, Any],
    status: OutboxStatus,
    zalo_message_id: str | None = None,
    provider_message_id: str | None = None,
    last_error: str | None = None,
    runtime_revision_id=None,
    authority_generation: int | None = None,
    runtime_fingerprint: str | None = None,
    origin_kind: str | None = None,
    fence_scope: str | None = None,
) -> OutboundOutbox | None:
    """Insert (or upsert) an outbox row for ``message_id``.

    Called from ``record_bot_outcome`` in the SAME transaction as the message
    write. The unique constraint on ``message_id`` means a second call for the
    same message is a no-op (returns the existing row) — defends against a
    crash-and-retry that re-records the same outcome.

    ``status`` is the FINAL dispatch status (SENT / FAILED / SEND_UNKNOWN /
    SUPPRESSED). The inline send path records the final state directly; only
    crashes leave rows in SENDING (which the sweep handles).

    Returns the row, or None if the insert was skipped (best-effort: errors are
    logged and swallowed because the outbox is observability/reliability
    infrastructure, not a turn-blocking dependency).
    """
    try:
        # INSERT ... ON CONFLICT (message_id) DO UPDATE so a retry after a
        # crash re-records the final state rather than failing.
        from sqlalchemy.dialects.postgresql import insert as pg_insert

        insert_stmt = pg_insert(OutboundOutbox).values(
            message_id=message_id,
            channel=channel,
            payload=payload,
            status=status.value if isinstance(status, OutboxStatus) else status,
            zalo_message_id=zalo_message_id,
            provider_message_id=provider_message_id or zalo_message_id,
            last_error=last_error,
            runtime_revision_id=runtime_revision_id,
            authority_generation=authority_generation,
            runtime_fingerprint=runtime_fingerprint,
            origin_kind=origin_kind,
            fence_scope=fence_scope,
            sent_at=datetime.now(timezone.utc) if status == OutboxStatus.SENT else None,
            updated_at=datetime.now(timezone.utc),
        )
        stmt = insert_stmt.on_conflict_do_update(
            index_elements=["message_id"],
            set_={
                "status": insert_stmt.excluded.status,
                "zalo_message_id": insert_stmt.excluded.zalo_message_id,
                "provider_message_id": insert_stmt.excluded.provider_message_id,
                "last_error": insert_stmt.excluded.last_error,
                "sent_at": insert_stmt.excluded.sent_at,
                "updated_at": insert_stmt.excluded.updated_at,
                "runtime_revision_id": insert_stmt.excluded.runtime_revision_id,
                "authority_generation": insert_stmt.excluded.authority_generation,
                "runtime_fingerprint": insert_stmt.excluded.runtime_fingerprint,
                "origin_kind": insert_stmt.excluded.origin_kind,
                "fence_scope": insert_stmt.excluded.fence_scope,
            },
        ).returning(OutboundOutbox)
        result = await db.execute(stmt)
        row = result.scalar_one_or_none()
        return row
    except Exception:  # noqa: BLE001 — outbox is best-effort, never blocks a turn
        logger.warning("outbox enqueue failed for message_id=%s", message_id, exc_info=True)
        return None


async def claim_stale_sending(
    db: AsyncSession,
    *,
    stale_threshold_seconds: int = 30,
    batch_size: int = 10,
) -> list[DispatchCandidate]:
    """Claim rows stuck in SENDING older than the threshold for re-dispatch.

    Uses ``FOR UPDATE SKIP LOCKED`` so multiple sweepers (or reconcile + sweep)
    don't double-claim. The transaction is committed by the caller after each
    row is re-dispatched.

    SEND_UNKNOWN rows are NEVER returned (Zalo may have accepted — re-sending
    would duplicate). SENT/SUPPRESSED rows are terminal.
    """
    threshold = datetime.now(timezone.utc) - timedelta(seconds=stale_threshold_seconds)
    try:
        rows = (
            await db.execute(
                text(
                    "SELECT id, message_id, channel, payload FROM outbound_outbox "
                    "WHERE status = 'SENDING' AND updated_at < :threshold "
                    "ORDER BY created_at LIMIT :batch FOR UPDATE SKIP LOCKED"
                ),
                {"threshold": threshold, "batch": batch_size},
            )
        ).all()
        return [
            DispatchCandidate(
                outbox_id=r.id,
                message_id=r.message_id,
                channel=r.channel,
                payload=r.payload if isinstance(r.payload, dict) else {},
            )
            for r in rows
        ]
    except Exception:  # noqa: BLE001
        logger.warning("outbox claim_stale_sending failed", exc_info=True)
        return []


async def mark_status(
    db: AsyncSession,
    *,
    outbox_id: int,
    status: OutboxStatus,
    zalo_message_id: str | None = None,
    last_error: str | None = None,
) -> None:
    """Update an outbox row's status after a dispatch attempt."""
    try:
        values: dict[str, Any] = {
            "status": status.value if isinstance(status, OutboxStatus) else status,
            "updated_at": datetime.now(timezone.utc),
            "attempts": OutboundOutbox.attempts + 1,
        }
        if status == OutboxStatus.SENT:
            values["sent_at"] = datetime.now(timezone.utc)
            if zalo_message_id is not None:
                values["zalo_message_id"] = zalo_message_id
        if last_error is not None:
            values["last_error"] = last_error[:500]
        await db.execute(
            update(OutboundOutbox).where(OutboundOutbox.id == outbox_id).values(**values)
        )
    except Exception:  # noqa: BLE001
        logger.warning("outbox mark_status failed for id=%s", outbox_id, exc_info=True)


async def count_by_status(db: AsyncSession, *, since: datetime) -> dict[str, int]:
    """Count outbox rows by status since ``since`` (for the duplicate-outbound SLO)."""
    try:
        rows = (
            await db.execute(
                text(
                    "SELECT status, COUNT(*) AS n FROM outbound_outbox "
                    "WHERE created_at >= :since GROUP BY status"
                ),
                {"since": since},
            )
        ).all()
        return {r.status: int(r.n) for r in rows}
    except Exception:  # noqa: BLE001
        return {}
