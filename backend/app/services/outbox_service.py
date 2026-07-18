"""Outbound transactional outbox service (Tech-Lead Directive §14).

Records the dispatch intent for every outbound BOT message in the same DB
transaction as the message write. The outbox row is the authoritative
"was this sent?" record:

- Reconcile reads it to detect duplicates (the duplicate_outbound_rate SLO finally
  has a data source).
- The dispatcher sweep re-dispatches rows stuck in SENDING older than a
  threshold; SEND_UNKNOWN rows are NEVER re-dispatched (Zalo may have accepted).
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
from app.graph.outbound_telemetry import OutboundTelemetry

logger = logging.getLogger(__name__)


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


def build_outbox_payload(
    chat_id: str, text: str, quote_message_id: str | None = None
) -> dict[str, str]:
    """Create the immutable provider payload stored with an outbound command."""
    payload = {"chat_id": chat_id, "text": text}
    if quote_message_id:
        payload["quote_message_id"] = quote_message_id
    return payload


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
) -> OutboundOutbox:
    """Persist a command before provider I/O in the caller's transaction.

    Unlike the legacy outcome recorder this deliberately does not swallow an
    insert error: acknowledging a reply without its durable command would make
    crash recovery impossible.
    """
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    now = datetime.now(timezone.utc)
    stmt = (
        pg_insert(OutboundOutbox)
        .values(
            message_id=message_id,
            channel=channel,
            payload=payload,
            status=OutboxStatus.PENDING.value,
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


async def dispatch_outbox(db: AsyncSession, *, outbox_id: int) -> DispatchResult | None:
    """Claim, authorize, and send an immutable command.

    Runtime-bound commands hold a shared PostgreSQL advisory lock after their
    active-authority check. The caller finalizes the command in this same
    transaction, so an activation's exclusive lock cannot interleave between
    authorization and the provider request or its durable classification.
    """
    outbox = await db.get(OutboundOutbox, outbox_id)
    if outbox is None or outbox.status != OutboxStatus.PENDING.value:
        return None

    if outbox.fence_scope == "RUNTIME":
        from app.services.installation.authority import RuntimeAuthorityStamp
        from app.services.installation.repository import InstallationRepository
        from app.services.installation.service import InstallationService

        await InstallationRepository(db).acquire_runtime_dispatch_lock()
        stamp_complete = (
            outbox.runtime_revision_id is not None
            and outbox.authority_generation is not None
            and outbox.runtime_fingerprint is not None
        )
        stamp_is_current = False
        if stamp_complete:
            stamp_is_current = await InstallationService(db).runtime_stamp_is_current(
                RuntimeAuthorityStamp(
                    revision_id=outbox.runtime_revision_id,
                    authority_generation=outbox.authority_generation,
                    fingerprint=outbox.runtime_fingerprint,
                )
            )
        if not stamp_is_current:
            candidate = await claim_pending_outbox(db, outbox_id=outbox_id)
            if candidate is None:
                return None
            return DispatchResult(
                outbox_id=candidate.outbox_id,
                message_id=candidate.message_id,
                ok=False,
                error="runtime authority changed before outbound dispatch",
                error_class="policy_suppressed",
                suppressed=True,
            )

    candidate = await claim_pending_outbox(db, outbox_id=outbox_id)
    if candidate is None:
        return None

    from app.services.integration_settings import IntegrationSettingsService
    from app.services.zalo_sender import ZaloChannelSender

    integration_settings = IntegrationSettingsService(db)
    cfg = await integration_settings.resolve_zalo()

    # Channel-neutral dispatch path (Phase 3): route through the registry when
    # the outbox channel maps to a registered provider. Falls back to the legacy
    # ZaloChannelSender for payloads that do not (e.g. a yet-unmapped channel).
    dispatch_result = await _try_neutral_dispatch(db, candidate, outbox, cfg, integration_settings)
    if dispatch_result is not None:
        return dispatch_result

    # Legacy path: direct ZaloChannelSender (unchanged behavior).
    sender = ZaloChannelSender(cfg, refresh=lambda: integration_settings.refresh_oa_access_token())
    result = await sender.send_payload(candidate.channel, candidate.payload)
    return DispatchResult(
        outbox_id=candidate.outbox_id,
        message_id=candidate.message_id,
        ok=result.ok,
        zalo_message_id=result.msg_id,
        error=result.error,
        error_class=result.error_class,
        telemetry=result.telemetry,
    )


async def _try_neutral_dispatch(
    db: AsyncSession,
    candidate: DispatchCandidate,
    outbox: OutboundOutbox,
    cfg,
    integration_settings,
) -> DispatchResult | None:
    """Attempt registry-driven dispatch; return None to fall back to legacy.

    Builds an :class:`OutboundTextCommand` from the outbox row's Zalo-shaped
    payload (``chat_id``/``text``/``quote_message_id``) and routes it through
    :class:`ChannelDispatchService`. The authority fence uses the outbox row's
    ``channel_account_generation`` when present (Phase 2 column).
    """
    from app.channels import types as ct
    from app.channels.dispatch import (
        ChannelDispatchService,
        build_zalo_registry_from_config,
    )
    from app.channels.registry import ChannelAdapterRegistry

    provider = _provider_for_outbox_channel(candidate.channel)
    if provider is None:
        return None  # unmapped channel → legacy path

    if provider == ct.PROVIDER_FACEBOOK_MESSENGER:
        # Messenger: resolve the active Page config + account_key from the
        # conversation's channel identity. The Page token is decrypted
        # server-side via the FacebookAccountResolver.
        return await _dispatch_facebook(
            db, candidate, outbox, integration_settings
        )

    # Zalo path: build a Zalo registry + hardcode the stable account keys.
    registry: ChannelAdapterRegistry = build_zalo_registry_from_config(
        cfg,
        oa_refresh=lambda: integration_settings.refresh_oa_access_token(),
    )
    if registry.get(provider) is None:
        return None  # adapter not registered → legacy path

    text = str(candidate.payload.get("text") or "")
    recipient_id = str(candidate.payload.get("chat_id") or "")
    if not text or not recipient_id:
        return DispatchResult(
            outbox_id=candidate.outbox_id,
            message_id=candidate.message_id,
            ok=False,
            error="outbound payload is missing chat_id or text",
            error_class="provider_error",
        )

    account_key = "default:zalo_oa" if provider == ct.PROVIDER_ZALO_OA else "default:zalo_bot"

    # NOTE(Phase 4): legacy rows have channel_account_generation = NULL → coerced
    # to 0 here. That is safe today because ChannelDispatchService is wired with
    # account_resolver=None (the fence is skipped). The moment a resolver is
    # wired, every legacy row will compare account.generation (≥1, from Alembic
    # 0047) > 0 and be suppressed. Before wiring the resolver, either stamp
    # channel_account_generation on create_pending_outbox or run a one-shot
    # backfill re-stamping existing PENDING rows with the current generation.
    command = ct.OutboundTextCommand(
        provider=provider,
        account_key=account_key,
        recipient_id=recipient_id,
        text=text,
        channel_account_generation=int(outbox.channel_account_generation or 0),
        reply_to_message_id=candidate.payload.get("quote_message_id") or None,
    )
    svc = ChannelDispatchService(registry)
    result = await svc.send(command)
    return DispatchResult(
        outbox_id=candidate.outbox_id,
        message_id=candidate.message_id,
        ok=result.ok,
        zalo_message_id=result.provider_message_id,
        provider_message_id=result.provider_message_id,
        error=result.error,
        error_class=result.error_class,
        suppressed=result.suppressed,
        telemetry=result.telemetry,
    )


async def _dispatch_facebook(
    db: AsyncSession,
    candidate: DispatchCandidate,
    outbox: OutboundOutbox,
    integration_settings,
) -> DispatchResult | None:
    """Dispatch a Messenger outbound command through the neutral registry.

    Resolves the active Page config (decrypting the Page token server-side),
    the account_key + recipient from the conversation's channel identity, and
    wires the :class:`FacebookAccountResolver` so the channel-account authority
    fence (generation check) is enforced — a stale command queued across a
    Page disconnect/reconnect is suppressed rather than sent.
    """
    from app.channels import types as ct
    from app.channels.dispatch import ChannelDispatchService, build_facebook_registry
    from app.channels.providers.facebook_account import FacebookAccountResolver

    # 1. Resolve the conversation → channel identity → account_key + external_id.
    from app.models.conversation import Conversation, Message
    from app.models.contact import ContactChannelIdentity
    from sqlalchemy import select

    msg = await db.get(Message, candidate.message_id)
    if msg is None:
        return None
    row = (
        await db.execute(
            select(
                ContactChannelIdentity.account_key,
                ContactChannelIdentity.external_id,
            )
            .select_from(Conversation)
            .join(
                ContactChannelIdentity,
                Conversation.channel_identity_id == ContactChannelIdentity.id,
            )
            .where(Conversation.id == msg.conversation_id)
        )
    ).first()
    if row is None:
        return None  # no identity → legacy path cannot help either; suppress
    account_key, recipient_id = row.account_key, row.external_id

    # 2. Resolve the active Page config. resolve_facebook decrypts the Page
    #    token with the page_id-bound AEAD context (Phase 4).
    fb_cfg = await integration_settings.resolve_facebook(account_key)
    if fb_cfg is None:
        return DispatchResult(
            outbox_id=candidate.outbox_id,
            message_id=candidate.message_id,
            ok=False,
            error="facebook page token not resolvable (reconnect required)",
            error_class="auth_revoked",
            suppressed=True,
        )

    text = str(candidate.payload.get("text") or "")
    if not text:
        return DispatchResult(
            outbox_id=candidate.outbox_id,
            message_id=candidate.message_id,
            ok=False,
            error="outbound payload is missing text",
            error_class="provider_error",
        )

    registry = build_facebook_registry(fb_cfg)
    resolver = FacebookAccountResolver(db)
    command = ct.OutboundTextCommand(
        provider=ct.PROVIDER_FACEBOOK_MESSENGER,
        account_key=account_key,
        recipient_id=recipient_id,
        text=text,
        channel_account_generation=int(outbox.channel_account_generation or 0),
        reply_to_message_id=candidate.payload.get("quote_message_id") or None,
    )
    svc = ChannelDispatchService(registry, account_resolver=resolver)
    result = await svc.send(command)
    return DispatchResult(
        outbox_id=candidate.outbox_id,
        message_id=candidate.message_id,
        ok=result.ok,
        zalo_message_id=result.provider_message_id,
        provider_message_id=result.provider_message_id,
        error=result.error,
        error_class=result.error_class,
        suppressed=result.suppressed,
        telemetry=result.telemetry,
    )


def _provider_for_outbox_channel(channel: str) -> str | None:
    """Map the outbox row's channel string to a neutral provider id.

    The outbox ``channel`` column carries provider ids directly
    (``zalo_bot`` / ``zalo_oa`` / ``facebook_messenger``). Returns ``None`` for
    any unrecognized value so the caller falls back to the legacy sender.
    """
    from app.channels import types as ct

    if channel in (
        ct.PROVIDER_ZALO_BOT,
        ct.PROVIDER_ZALO_OA,
        ct.PROVIDER_FACEBOOK_MESSENGER,
    ):
        return channel
    return None


async def dispatch_message_outbox(db: AsyncSession, *, message_id: int) -> DispatchResult | None:
    """Dispatch the single durable command belonging to ``message_id``."""
    outbox_id = await db.scalar(
        select(OutboundOutbox.id).where(OutboundOutbox.message_id == message_id)
    )
    if outbox_id is None:
        return None
    return await dispatch_outbox(db, outbox_id=int(outbox_id))


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
