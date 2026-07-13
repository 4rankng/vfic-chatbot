"""Outbound transactional outbox service (Tech-Lead Directive §14).

Records the dispatch intent for every outbound BOT message in the same DB
transaction as the message write. The outbox row is the authoritative
"was this sent?" record:

- Reconcile reads it to detect duplicates (the duplicate_outbound_rate SLO finally
  has a data source).
- The dispatcher sweep re-dispatches rows stuck in SENDING older than a
  threshold; SEND_UNKNOWN rows are NEVER re-dispatched (Zalo may have accepted).
- A unique constraint on message_id prevents double-enqueue.

Conservative design — preserves the inline-send behavior:
- ``runner.py`` still calls ``zalo.send_message`` inline (battle-tested, low
  latency).
- ``enqueue_outbox`` writes the row with the FINAL status (SENT / FAILED /
  SEND_UNKNOWN / SUPPRESSED) in the same transaction as
  ``record_bot_outcome``. The "PENDING→SENDING→SENT" progression happens
  inline; the table records the outcome.
- A sweep (``claim_stale_sending``) finds rows left in SENDING by a crash and
  re-dispatches them. This is the safety net; the inline path is the norm.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.outbox import OutboxStatus, OutboundOutbox

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DispatchCandidate:
    """A row claimed by the dispatcher sweep for re-dispatch."""

    outbox_id: int
    message_id: int
    channel: str
    payload: dict[str, Any]


async def enqueue_outbox(
    db: AsyncSession,
    *,
    message_id: int,
    channel: str,
    payload: dict[str, Any],
    status: OutboxStatus,
    zalo_message_id: str | None = None,
    last_error: str | None = None,
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

        stmt = (
            pg_insert(OutboundOutbox)
            .values(
                message_id=message_id,
                channel=channel,
                payload=payload,
                status=status.value if isinstance(status, OutboxStatus) else status,
                zalo_message_id=zalo_message_id,
                last_error=last_error,
                sent_at=datetime.now(timezone.utc) if status == OutboxStatus.SENT else None,
                updated_at=datetime.now(timezone.utc),
            )
            .on_conflict_do_update(
                index_elements=["message_id"],
                set_={
                    "status": pg_insert.excluded.status,
                    "zalo_message_id": pg_insert.excluded.zalo_message_id,
                    "last_error": pg_insert.excluded.last_error,
                    "sent_at": pg_insert.excluded.sent_at,
                    "updated_at": pg_insert.excluded.updated_at,
                },
            )
            .returning(OutboundOutbox)
        )
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
        from sqlalchemy import update

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
        await db.execute(update(OutboundOutbox).where(OutboundOutbox.id == outbox_id).values(**values))
    except Exception:  # noqa: BLE001
        logger.warning("outbox mark_status failed for id=%s", outbox_id, exc_info=True)


async def count_by_status(
    db: AsyncSession, *, since: datetime
) -> dict[str, int]:
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
