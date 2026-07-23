"""Conversation state mutations + orchestration (the takeover race-guard core).

All state changes bump ``version`` (the optimistic-lock token) and fan out a realtime
event via the event bus.

Reads live in ``repository.py``; realtime publishing in ``events.py``.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, or_, select, text, update

from app.conversation_messaging.application.ports import (
    ConversationEventsPort,
    DeliveryResultPort,
)
from app.conversation_messaging.domain.delivery import delivery_rank, receipt_advances
from app.conversation_messaging.domain.ownership import (
    lock_owner_matches as _lock_owner_matches,
    lock_still_live as _lock_still_live,
    normalize_lock_owner as _normalize_lock_owner,
)
from app.core.config import PROACTIVE_OPTOUT_PHRASES, get_settings
from app.schemas.bot_run import parse_decision_trace
from app.models.conversation import (
    BotRun,
    BotRunOutcome,
    Conversation,
    ConversationMode,
    ConversationProjectState,
    ConversationStatus,
    DeliveryStatus,
    Message,
    MessageSender,
)
from app.models.user import Role, User
from app.services.audit_service import record_audit
from app.shared.application.outbound import OutboundTelemetry, is_ambiguous_send

_settings = get_settings()
_SEMI_AUTO_INACTIVITY = timedelta(minutes=5)

logger = logging.getLogger(__name__)


def _delivery_status_for_send_error(error_class: str | None, *, ok: bool):
    return DeliveryStatus.SEND_UNKNOWN if is_ambiguous_send(error_class, ok=ok) else None

class ConversationConflict(Exception):
    """Raised when a recruiter tries to take over a conversation owned by another."""

    def __init__(self, message: str = "", owner_name: str | None = None) -> None:
        super().__init__(message)
        self.owner_name = owner_name


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


async def _fetch_owner_name(db, conv: Conversation) -> str | None:
    """Look up the full name of the current owner of *conv*.

    Used by :meth:`take_over` and :meth:`semi_auto` when a conditional
    UPDATE fails, to produce a rich ``ConversationConflict`` message.
    """
    from sqlalchemy import select

    from app.models.user import User as UserModel

    owner_row = await db.scalar(
        select(UserModel.full_name).where(UserModel.id == conv.assigned_recruiter_id)
    )
    return owner_row or None


class ConversationState:
    """Mutates conversation/message rows + records audit + publishes realtime events.

    Composes a ``ConversationRepository`` (for reads within mutations) and a
    ``ConversationEventBus`` (for publishing). Pure orchestration — no new business
    rules.
    """

    def __init__(self, db, repo, events: ConversationEventsPort) -> None:
        self.db = db
        self.repo = repo
        self.events = events

    # --- webhook-side primitives (used by US-006 chatbot) ---
    async def ensure(self, zalo_chat_id: str, *, zalo_channel: str = "bot") -> Conversation:
        """Compatibility facade: resolve a Zalo (channel, chat_id) to the neutral
        identity and delegate to :meth:`ensure_by_identity`.

        Retained during the Zalo→neutral migration (Phase 2–3) so existing
        webhook/sender callers keep working. New code should call
        ``ensure_by_identity`` directly. The Zalo account keys are the stable
        synthetic values backfilled by Alembic 0047. OA's ``oa:`` storage prefix
        is stripped from the external id, matching the backfill normalization.
        """
        if zalo_channel == "oa":
            provider = "zalo_oa"
            account_key = "default:zalo_oa"
            external_id = zalo_chat_id.removeprefix("oa:") if zalo_chat_id.startswith("oa:") else zalo_chat_id
        else:
            provider = "zalo_bot"
            account_key = "default:zalo_bot"
            external_id = zalo_chat_id
        return await self.ensure_by_identity(
            provider=provider,
            account_key=account_key,
            external_id=external_id,
            zalo_chat_id_alias=zalo_chat_id,
            zalo_channel_alias=zalo_channel,
        )

    async def ensure_by_identity(
        self,
        *,
        provider: str,
        account_key: str,
        external_id: str,
        zalo_chat_id_alias: str | None = None,
        zalo_channel_alias: str | None = None,
    ) -> Conversation:
        """Canonical create-or-fetch keyed by (provider, account_key, external_id).

        Atomically ensures a Contact + ContactChannelIdentity + Conversation for
        the neutral triple. The Contact is created one-per-identity (matching the
        1:1 conversation/identity invariant).

        Concurrency: the check-then-insert sequence has a TOCTOU window. Two
        first-contact events for the same triple may both pass the initial
        ``get_by_identity`` lookup and race on insert. The DB partial unique
        indexes (``uq_contact_channel_authority`` on the identity triple,
        ``uq_conversations_channel_identity`` on the conversation) are the final
        authority: the loser raises ``IntegrityError`` on flush, which we catch,
        roll back, and refetch the winner. This is safer than relying on
        ``MessageDedupService`` (which gates on zalo_chat_id+msg_hash and does
        not cover OA side events or future Messenger entry points).

        ``zalo_chat_id_alias`` / ``zalo_channel_alias`` populate the nullable
        compatibility columns for Zalo rows so legacy reads keep working during
        the migration. They stay NULL for Messenger (no Zalo equivalent).
        """
        from sqlalchemy.exc import IntegrityError

        from app.models.contact import Contact, ContactChannelIdentity

        conv = await self.repo.get_by_identity(
            provider=provider, account_key=account_key, external_id=external_id
        )
        if conv is not None:
            # Backfill a missing Zalo alias on an existing row (defensive).
            if zalo_chat_id_alias and not conv.zalo_chat_id:
                conv.zalo_chat_id = zalo_chat_id_alias
            if zalo_channel_alias and (
                not conv.zalo_channel or conv.zalo_channel == "bot"
            ) and zalo_channel_alias != "bot":
                conv.zalo_channel = zalo_channel_alias
            await self.db.flush()
            return conv

        try:
            # Resolve or create the Contact + identity in the same transaction.
            identity = (
                await self.db.scalars(
                    select(ContactChannelIdentity).where(
                        ContactChannelIdentity.provider == provider,
                        ContactChannelIdentity.account_key == account_key,
                        ContactChannelIdentity.external_id == external_id,
                    )
                )
            ).first()
            if identity is None:
                contact = Contact()
                self.db.add(contact)
                await self.db.flush()
                identity = ContactChannelIdentity(
                    contact_id=contact.id,
                    provider=provider,
                    account_key=account_key,
                    external_id=external_id,
                )
                self.db.add(identity)
                await self.db.flush()

            conv = Conversation(
                zalo_chat_id=zalo_chat_id_alias,
                zalo_channel=zalo_channel_alias or "bot",
                contact_id=identity.contact_id,
                channel_identity_id=identity.id,
            )
            self.db.add(conv)
            await self.db.flush()
            return conv
        except IntegrityError:
            # A concurrent ensure_by_identity won the identity/conversation
            # unique constraint. Roll back this transaction's pending inserts
            # and refetch the winner. The rollback is safe because the caller's
            # transaction will continue with the refetched row (the dedup claim
            # and message write are the caller's responsibility).
            await self.db.rollback()
            winner = await self.repo.get_by_identity(
                provider=provider, account_key=account_key, external_id=external_id
            )
            if winner is None:  # pragma: no cover - defensive; race already resolved
                raise
            return winner

    def semi_auto_inactive(self, conv: Conversation) -> bool:
        reference = conv.taken_over_at or conv.updated_at
        if reference is None:
            return True
        if reference.tzinfo is None:
            reference = reference.replace(tzinfo=timezone.utc)
        return utcnow() - reference >= _SEMI_AUTO_INACTIVITY

    def run_start_guard(self, conv: Conversation) -> bool:
        """True only when the bot may run.

        BOT is always eligible. SEMI_AUTO is eligible after the assigned human has
        been inactive for five minutes. HUMAN/CLOSED starve the bot.
        """
        if conv.mode == ConversationMode.BOT:
            return True
        if conv.mode == ConversationMode.SEMI_AUTO:
            return self.semi_auto_inactive(conv)
        return False

    async def record_inbound(
        self,
        conv: Conversation,
        *,
        body: str,
        zalo_message_id: str | None = None,
        provider_message_id: str | None = None,
        runtime_revision_id: uuid.UUID | None = None,
        authority_generation: int | None = None,
        runtime_fingerprint: str | None = None,
    ) -> Message:
        """Persist an inbound worker message and update conversation attention state.

        ``provider_message_id`` is the canonical neutral message id (Alembic
        0047). ``zalo_message_id`` remains as a compatibility alias; when only
        ``zalo_message_id`` is supplied, it is copied to ``provider_message_id``
        so the durable inbound idempotency index applies to Zalo rows too.
        """
        neutral_id = provider_message_id or zalo_message_id
        msg = Message(
            conversation_id=conv.id,
            sender=MessageSender.WORKER,
            body=body,
            zalo_message_id=zalo_message_id,
            provider_message_id=neutral_id,
            runtime_revision_id=runtime_revision_id,
            authority_generation=authority_generation,
            runtime_fingerprint=runtime_fingerprint,
        )
        self.db.add(msg)
        conv.last_inbound_at = utcnow()
        # Proactive opt-out: cheap substring scan on the hot path. Accepted
        # tradeoff (A7) — atomicity with the inbound txn outweighs purity.
        _lower = body.strip().lower()
        if _lower and any(p in _lower for p in PROACTIVE_OPTOUT_PHRASES):
            conv.followup_opted_out = True
            logger.info(
                "proactive opt-out: conversation=%s phrase detected",
                conv.zalo_chat_id,
            )
        if conv.mode != ConversationMode.BOT:
            conv.unread_count = (conv.unread_count or 0) + 1
        conv.version += 1
        conv.conversation_seq += 1
        await self.db.flush()
        await self.db.commit()
        await self.db.refresh(msg)
        await self.events.message_created(msg, conv)
        await self.events.conversation_updated(conv)
        return msg

    async def escalate_extracted_intent(
        self,
        conv: Conversation,
        *,
        reason: str,
        confidence: float,
        expected_version: int,
    ) -> bool:
        """Move an extraction-classified contact to human-only review.

        Candidate extraction runs after the chatbot reply has already been sent.
        This transition therefore controls future turns only. A conditional
        update makes concurrent persistence jobs create one note and audit event,
        while the expected version prevents stale results from overriding a newer
        inbound or recruiter decision.
        """
        target_state = and_(
            Conversation.mode == ConversationMode.HUMAN,
            Conversation.needs_human.is_(True),
        )
        transition = await self.db.execute(
            update(Conversation)
            .where(
                Conversation.id == conv.id,
                Conversation.version == expected_version,
                Conversation.status != ConversationStatus.CLOSED,
                ~target_state,
            )
            .values(
                mode=ConversationMode.HUMAN,
                status=ConversationStatus.OPEN,
                needs_human=True,
                bot_locked_until=None,
                bot_lock_owner=None,
                bot_lock_heartbeat_at=None,
                version=Conversation.version + 1,
                conversation_seq=Conversation.conversation_seq + 1,
            )
            .returning(Conversation.version)
            .execution_options(synchronize_session=False)
        )
        transitioned_version = transition.scalar_one_or_none()
        if transitioned_version is None:
            await self.db.rollback()
            return False

        system_note = Message(
            conversation_id=conv.id,
            sender=MessageSender.SYSTEM,
            body="Luồng trích xuất đề nghị nhân viên xác minh ý định liên hệ.",
        )
        self.db.add(system_note)
        await record_audit(
            self.db,
            action="extraction_intent_human_review",
            target_type="conversation",
            target_id=str(conv.id),
            payload={
                "reason": reason,
                "confidence": round(confidence, 4),
                "version": transitioned_version,
            },
        )

        await self.db.commit()
        await self.db.refresh(system_note)
        await self.db.refresh(conv)
        await self.events.message_created(system_note, conv)
        await self.events.conversation_updated(conv)
        return True

    async def acquire_lock(
        self,
        conv_id: uuid.UUID,
        ttl_seconds: int | None = None,
        lock_owner: uuid.UUID | str | None = None,
    ) -> uuid.UUID | None:
        """Per-chat mutex via bot_locked_until. Atomic: only one run holds it at a time.

        TTL defaults to settings.bot_lock_ttl_seconds, which is sized to exceed the
        worst-case single turn (a worker crash mid-turn is recovered by TTL expiry;
        the owner token makes stale jobs unable to clear a newer job's lock).
        """
        ttl = ttl_seconds if ttl_seconds is not None else _settings.bot_lock_ttl_seconds
        now = utcnow()
        locked_until = now + timedelta(seconds=ttl)
        owner = _normalize_lock_owner(lock_owner) or uuid.uuid4()
        res = await self.db.execute(
            update(Conversation)
            .where(
                Conversation.id == conv_id,
                Conversation.mode.in_((ConversationMode.BOT, ConversationMode.SEMI_AUTO)),
                or_(
                    Conversation.bot_locked_until.is_(None),
                    Conversation.bot_locked_until < utcnow(),
                ),
            )
            .values(
                bot_locked_until=locked_until,
                bot_lock_owner=owner,
                bot_lock_heartbeat_at=now,
            )
            .execution_options(synchronize_session=False)
        )
        await self.db.commit()
        return owner if res.rowcount == 1 else None

    async def release_lock(
        self, conv: Conversation, lock_owner: uuid.UUID | str | None = None
    ) -> None:
        owner = _normalize_lock_owner(lock_owner)
        if owner is None:
            conv.bot_locked_until = None
            conv.bot_lock_owner = None
            conv.bot_lock_heartbeat_at = None
            await self.db.commit()
            return

        res = await self.db.execute(
            update(Conversation)
            .where(Conversation.id == conv.id, Conversation.bot_lock_owner == owner)
            .values(
                bot_locked_until=None,
                bot_lock_owner=None,
                bot_lock_heartbeat_at=None,
            )
            .execution_options(synchronize_session=False)
        )
        await self.db.commit()
        if res.rowcount == 1:
            conv.bot_locked_until = None
            conv.bot_lock_owner = None
            conv.bot_lock_heartbeat_at = None

    async def renew_lock(
        self, conv_id: uuid.UUID, *, lock_owner: uuid.UUID | str, ttl_seconds: int | None = None
    ) -> bool:
        """Renew a live turn's lease only when it still owns the lock."""
        owner = _normalize_lock_owner(lock_owner)
        if owner is None:
            return False
        ttl = ttl_seconds if ttl_seconds is not None else _settings.bot_lock_ttl_seconds
        now = utcnow()
        res = await self.db.execute(
            update(Conversation)
            .where(
                Conversation.id == conv_id,
                Conversation.bot_lock_owner == owner,
                Conversation.bot_locked_until > now,
            )
            .values(
                bot_locked_until=now + timedelta(seconds=ttl),
                bot_lock_heartbeat_at=now,
            )
            .execution_options(synchronize_session=False)
        )
        await self.db.commit()
        return res.rowcount == 1

    async def break_stale_lock(self, conv_id: uuid.UUID, *, stale_after_seconds: int) -> bool:
        """Force-clear a per-chat mutex whose owner heartbeat is stale (older than
        ``stale_after_seconds``), so a crashed/killed worker does not stall the
        conversation until ``bot_lock_ttl`` expires.

        Conditional on heartbeat age: a live, actively-processing turn has a
        fresh heartbeat (set at ``acquire_lock``; a normal turn finishes well
        inside ``chat_turn_job_timeout``) and is never stolen. Only a wedged job
        whose heartbeat predates the RQ kill threshold qualifies. Safe to compose
        with ``claim_send``: a not-yet-reaped old turn that reaches its send
        after its lock was stolen fails the claim's ``lock_owner`` guard and
        suppresses rather than double-sending. Returns True iff a stale lock was
        cleared.
        """
        cutoff = utcnow() - timedelta(seconds=stale_after_seconds)
        res = await self.db.execute(
            update(Conversation)
            .where(
                Conversation.id == conv_id,
                Conversation.bot_locked_until.is_not(None),
                or_(
                    Conversation.bot_lock_heartbeat_at.is_(None),
                    Conversation.bot_lock_heartbeat_at < cutoff,
                ),
            )
            .values(
                bot_locked_until=None,
                bot_lock_owner=None,
                bot_lock_heartbeat_at=None,
            )
            .execution_options(synchronize_session=False)
        )
        await self.db.commit()
        return res.rowcount == 1

    async def recheck_ownership(
        self,
        conv: Conversation,
        version_at_start: int,
        lock_owner: uuid.UUID | str | None = None,
    ) -> bool:
        """Pre-send guard: bot may send only if eligible and version unchanged.

        IMPORTANT: the caller **must** run ``db.refresh(conv)`` immediately
        before calling this method (``expire_on_commit=False`` means the
        identity map hides concurrent takeovers).  Failing to refresh reads a
        stale in-memory ``version`` and may approve a send after a takeover.
        """
        if not self.run_start_guard(conv) or conv.version != version_at_start:
            return False
        if lock_owner is None:
            return True
        return _lock_owner_matches(conv.bot_lock_owner, lock_owner) and _lock_still_live(
            conv.bot_locked_until
        )

    async def claim_send(
        self,
        conv: Conversation,
        *,
        version_at_start: int,
        lock_owner: uuid.UUID | str | None,
        pending_message_id: int | None,
        reply: str,
        outbox_channel: str | None = None,
        outbox_payload: dict | None = None,
    ) -> bool:
        """Atomically claim the outbound send: flip the pending BOT row
        PENDING→SENDING (and stamp the real ``reply`` onto it) only if the
        conversation is still bot-owned at ``version_at_start`` with a live lock
        owned by ``lock_owner``.

        This is the pre-send gate that closes both the crash-window and the
        recheck→send TOCTOU in one conditional write: the claim commits only when
        the conversation ``version`` + lock ownership + lock liveness all still
        hold, so a recruiter takeover (clears ``bot_lock_owner``) or a newer
        inbound/recruiter reply (bumps ``version``) landing before the claim
        yields rowcount 0 and the caller suppresses instead of sending. The
        authoritative guard is the ``WHERE EXISTS`` below, evaluated server-side
        at commit time, so a stale identity-map snapshot cannot race it.

        The residual window after a successful claim is [claim-commit → Zalo
        POST], irreducible without a provider idempotency key (Zalo Bot Platform
        has none); a crash there leaves a SENDING row whose body is already the
        real reply (stamped here), so the reconcile sweep can resolve it as
        sent-but-unconfirmed (at-most-once) with correct content rather than
        re-enqueuing a duplicate or persisting the placeholder. Returns True iff
        the row was claimed.
        """
        if pending_message_id is None or lock_owner is None:
            # The atomic claim requires both a pending BOT row to flip and a lock
            # owner to gate on. Real turns always hold both (the webhook/reconcile
            # enqueue path acquires the lock and creates the pending row before the
            # send); refuse to claim so the caller suppresses rather than sending
            # without a durable ownership marker.
            return False
        owner = _normalize_lock_owner(lock_owner)
        res = await self.db.execute(
            text(
                """
                UPDATE messages SET delivery_status = 'SENDING', body = :reply
                 WHERE id = :pending_id
                   AND conversation_id = :cid
                   AND sender = 'BOT'
                   AND delivery_status = 'PENDING'
                   AND EXISTS (
                       SELECT 1 FROM conversations c
                        WHERE c.id = :cid
                          AND c.version = :version_at_start
                          AND c.bot_lock_owner = :owner
                          AND c.bot_locked_until IS NOT NULL
                          AND c.bot_locked_until > now()
                   )
                """
            ),
            {
                "pending_id": pending_message_id,
                "cid": conv.id,
                "version_at_start": version_at_start,
                "owner": owner,
                "reply": reply,
            },
        )
        if res.rowcount == 1 and outbox_channel is not None and outbox_payload is not None:
            from app.services.outbox_service import create_pending_outbox

            pending = await self.db.get(Message, pending_message_id)
            stamped = pending is not None and pending.runtime_revision_id is not None

            await create_pending_outbox(
                self.db,
                message_id=pending_message_id,
                channel=outbox_channel,
                payload=outbox_payload,
                runtime_revision_id=pending.runtime_revision_id if stamped else None,
                authority_generation=pending.authority_generation if stamped else None,
                runtime_fingerprint=pending.runtime_fingerprint if stamped else None,
                origin_kind="BOT" if stamped else None,
                fence_scope="RUNTIME" if stamped else None,
            )
        await self.db.commit()
        return res.rowcount == 1

    async def record_bot_outcome(
        self,
        conv: Conversation,
        *,
        version_at_start: int,
        reply: str,
        started_at: datetime,
        sent: bool,
        pending_message_id: int | None = None,
        external_error: str | None = None,
        zalo_message_id: str | None = None,
        stage_timings: dict | None = None,
        lock_owner: uuid.UUID | str | None = None,
        delivery_status: DeliveryStatus | None = None,
        trace_id: str | None = None,
        outcome_metadata: dict | None = None,
        decision_trace: dict | None = None,
        outbox_channel: str | None = None,
        outbox_payload: dict | None = None,
    ) -> Message:
        """Log a bot_run + BOT message; clears the lock.

        ``sent=False`` means either ownership suppression or delivery failure.
        ``external_error`` disambiguates real send failures so recovery can
        retry them instead of treating them as completed suppressed turns.

        ``delivery_status`` overrides the computed status. Used by the send path
        to stamp ``SEND_UNKNOWN`` when a transport exception may have reached
        Zalo (non-retriable — the reconciler skips these). When None, the status
        is derived from ``sent``/``external_error`` as before (backward compat).

        ``stage_timings`` is the per-stage wall-clock dict captured by run_turn
        (webhook_to_pickup / preamble / lane / lead / llm / safety / send /
        total). Persisted onto the BotRun for the performance dashboard; None
        on paths that don't instrument (e.g. legacy callers).

        ``outbox_channel`` + ``outbox_payload``: when both provided, an
        ``outbound_outbox`` row is written in THIS transaction (Tech-Lead
        Directive §14) so the outbox reflects the committed send outcome
        atomically. The channel is ``zalo_bot`` / ``zalo_oa``; the payload is
        the Zalo send body. Best-effort — outbox failures never block the turn.
        """
        if delivery_status is None:
            delivery_status = (
                DeliveryStatus.FAILED
                if external_error
                else DeliveryStatus.SENT
                if sent
                else DeliveryStatus.SUPPRESSED
            )
        outcome = (
            BotRunOutcome.SUPPRESSED
            if delivery_status == DeliveryStatus.SUPPRESSED
            else BotRunOutcome.ERROR
            if external_error
            else BotRunOutcome.SENT
            if sent
            else BotRunOutcome.SUPPRESSED
        )
        parsed_trace = parse_decision_trace(decision_trace)
        safe_decision_trace = (
            parsed_trace.model_dump(mode="json") if parsed_trace is not None else None
        )
        run = BotRun(
            conversation_id=conv.id,
            version_at_start=version_at_start,
            proposed_reply=reply,
            outcome=outcome,
            started_at=started_at,
            ended_at=utcnow(),
            stage_timings=stage_timings,
            trace_id=trace_id or None,
            outcome_metadata=outcome_metadata,
            decision_trace=safe_decision_trace,
        )
        msg = None
        pending_msg = None
        matched_pending = False
        resolved_delivery_status = delivery_status
        if pending_message_id is not None:
            pending_msg = await self.db.get(
                Message,
                pending_message_id,
                with_for_update=True,
            )
            if (
                pending_msg is not None
                and pending_msg.conversation_id == conv.id
                and pending_msg.sender == MessageSender.BOT
                and pending_msg.delivery_status
                in (
                    DeliveryStatus.PENDING,
                    DeliveryStatus.SENDING,
                    DeliveryStatus.SEND_UNKNOWN,
                    DeliveryStatus.SENT,
                    DeliveryStatus.DELIVERED,
                    DeliveryStatus.READ,
                )
            ):
                matched_pending = True
                run.runtime_revision_id = pending_msg.runtime_revision_id
                run.authority_generation = pending_msg.authority_generation
                run.runtime_fingerprint = pending_msg.runtime_fingerprint
        self.db.add(run)
        await self.db.flush()
        if matched_pending and pending_msg is not None:
            resolved_delivery_status = (
                pending_msg.delivery_status
                if delivery_rank(pending_msg.delivery_status)
                > delivery_rank(delivery_status)
                else delivery_status
            )
            pending_msg.body = reply
            pending_msg.bot_run_id = run.id
            pending_msg.delivery_status = resolved_delivery_status
            pending_msg.external_error = (
                None
                if delivery_rank(resolved_delivery_status)
                >= delivery_rank(DeliveryStatus.SENT)
                else external_error
            )
            if zalo_message_id:
                pending_msg.zalo_message_id = zalo_message_id
            msg = pending_msg
        if msg is None:
            msg = Message(
                conversation_id=conv.id,
                sender=MessageSender.BOT,
                body=reply,
                bot_run_id=run.id,
                delivery_status=delivery_status,
                external_error=external_error,
                zalo_message_id=zalo_message_id,
            )
            self.db.add(msg)
        owner = _normalize_lock_owner(lock_owner)
        if owner is None:
            conv.bot_locked_until = None
            conv.bot_lock_owner = None
            conv.bot_lock_heartbeat_at = None
        else:
            clear_res = await self.db.execute(
                update(Conversation)
                .where(Conversation.id == conv.id, Conversation.bot_lock_owner == owner)
                .values(
                    bot_locked_until=None,
                    bot_lock_owner=None,
                    bot_lock_heartbeat_at=None,
                    conversation_seq=Conversation.conversation_seq + 1,
                )
                .execution_options(synchronize_session=False)
            )
            if clear_res.rowcount == 1:
                conv.bot_locked_until = None
                conv.bot_lock_owner = None
                conv.bot_lock_heartbeat_at = None
        if delivery_rank(resolved_delivery_status) >= delivery_rank(
            DeliveryStatus.SENT
        ):
            conv.last_outbound_at = utcnow()
        # Bump the strict monotonic seq for every bot outcome (the key delta vs
        # `version`, which intentionally skips bot outcomes). The no-owner branch
        # touches conv in Python below; the owner branch bumped via SQL above.
        if owner is None:
            conv.conversation_seq = (conv.conversation_seq or 1) + 1
        # Transactional outbox (Tech-Lead Directive §14): record the dispatch
        # outcome in the same transaction as the message. Best-effort — outbox
        # failures never block the turn (logged in outbox_service).
        outbox_attempts = 0
        if outbox_channel is not None and outbox_payload is not None and msg.id is not None:
            from app.models.outbox import OutboxStatus
            from app.services.outbox_service import enqueue_outbox

            outbox_status = (
                OutboxStatus.SENT
                if delivery_rank(resolved_delivery_status)
                >= delivery_rank(DeliveryStatus.SENT)
                else OutboxStatus.SEND_UNKNOWN
                if resolved_delivery_status == DeliveryStatus.SEND_UNKNOWN
                else OutboxStatus.FAILED
                if resolved_delivery_status == DeliveryStatus.FAILED
                else OutboxStatus.SUPPRESSED
            )
            outbox = await enqueue_outbox(
                self.db,
                message_id=msg.id,
                channel=outbox_channel,
                payload=outbox_payload,
                status=outbox_status,
                zalo_message_id=msg.zalo_message_id,
                last_error=msg.external_error,
                runtime_revision_id=msg.runtime_revision_id,
                authority_generation=msg.authority_generation,
                runtime_fingerprint=msg.runtime_fingerprint,
                origin_kind="BOT" if msg.runtime_revision_id is not None else None,
                fence_scope="RUNTIME" if msg.runtime_revision_id is not None else None,
            )
            if outbox is not None:
                outbox_attempts = int(outbox.attempts or 0)
        await self.db.commit()
        await self.db.refresh(msg)
        msg._delivery_attempts = outbox_attempts
        await self.events.message_created(msg, conv)
        await self.events.conversation_updated(conv)
        return msg

    async def record_bot_pending(
        self,
        conv: Conversation,
        *,
        body: str = "Đang soạn trả lời...",
        runtime_revision_id: uuid.UUID | None = None,
        authority_generation: int | None = None,
        runtime_fingerprint: str | None = None,
    ) -> Message:
        """Persist a visible pending BOT row without touching the version guard."""
        msg = Message(
            conversation_id=conv.id,
            sender=MessageSender.BOT,
            body=body,
            delivery_status=DeliveryStatus.PENDING,
            runtime_revision_id=runtime_revision_id,
            authority_generation=authority_generation,
            runtime_fingerprint=runtime_fingerprint,
        )
        self.db.add(msg)
        await self.db.commit()
        await self.db.refresh(msg)
        # Realtime fan-out is deferred (fire-and-forget): payloads are serialized
        # eagerly on this coroutine (ORM attrs are expired post-commit and must
        # not be touched from the background task) and only the Redis publishes
        # run on it. See ConversationEventBus.schedule_realtime.
        self.events.schedule_realtime(msg, conv)
        return msg

    async def mark_stale_pending_failed(self, conv_id: uuid.UUID) -> int:
        """Flip any BOT/PENDING message rows for this conversation to FAILED.

        Call ONLY after ``acquire_lock()`` succeeded, so no live turn owns these
        rows.  Returns the number of rows updated.  No version bump, no
        ``last_outbound_at`` change, no events — the PENDING placeholder is
        ephemeral UI chrome that a crashed turn left behind.
        """
        res = await self.db.execute(
            update(Message)
            .where(
                Message.conversation_id == conv_id,
                Message.sender == MessageSender.BOT,
                Message.delivery_status == DeliveryStatus.PENDING,
            )
            .values(delivery_status=DeliveryStatus.FAILED)
            .execution_options(synchronize_session=False)
        )
        await self.db.commit()
        return res.rowcount

    async def resolve_unconfirmed_sending(self, conv_id: uuid.UUID) -> int:
        """Resolve a stale BOT/SENDING row as ``SEND_UNKNOWN``.

        A worker crash can happen either before or after Zalo accepts the POST.
        Retrying might duplicate the candidate-visible message, while declaring it
        sent would be false when the crash happened before the POST.  The terminal
        unknown state preserves that distinction and is never automatically retried.
        """
        res = await self.db.execute(
            update(Message)
            .where(
                Message.conversation_id == conv_id,
                Message.sender == MessageSender.BOT,
                Message.delivery_status == DeliveryStatus.SENDING,
            )
            .values(delivery_status=DeliveryStatus.SEND_UNKNOWN)
            .execution_options(synchronize_session=False)
        )
        if res.rowcount:
            from app.models.outbox import OutboxStatus, OutboundOutbox

            await self.db.execute(
                update(OutboundOutbox)
                .where(
                    OutboundOutbox.message_id.in_(
                        select(Message.id).where(
                            Message.conversation_id == conv_id,
                            Message.sender == MessageSender.BOT,
                            Message.delivery_status == DeliveryStatus.SEND_UNKNOWN,
                        )
                    ),
                    OutboundOutbox.status == OutboxStatus.SENDING.value,
                )
                .values(status=OutboxStatus.SEND_UNKNOWN.value, updated_at=utcnow())
                .execution_options(synchronize_session=False)
            )
        await self.db.commit()
        return res.rowcount

    # --- proactive follow-up ---

    async def record_proactive_outcome(
        self,
        conv: Conversation,
        *,
        message: str,
        result: DeliveryResultPort,
        lock_owner: uuid.UUID | str | None = None,
        pending_message_id: int | None = None,
        outbox_channel: str | None = None,
        outbox_payload: dict | None = None,
    ) -> Message:
        """Persist a proactive BOT message (no BotRun). Handles success/failure + cadence.

        On success: increments ``followup_count``, sets ``last_followup_at`` and
        ``last_outbound_at``, bumps version.  On failure: sets
        ``last_followup_attempt_at`` only (cadence budget is NOT consumed).
        Always clears the lock and fires realtime events.
        """
        delivery_status = DeliveryStatus.SENT if result.ok else DeliveryStatus.FAILED
        msg = await self.db.get(Message, pending_message_id) if pending_message_id else None
        if (
            msg is None
            or msg.conversation_id != conv.id
            or msg.sender != MessageSender.BOT
            or msg.delivery_status not in (DeliveryStatus.PENDING, DeliveryStatus.SENDING)
        ):
            msg = Message(
                conversation_id=conv.id,
                sender=MessageSender.BOT,
                body=message,
                delivery_status=delivery_status,
                zalo_message_id=result.msg_id,
                external_error=None if result.ok else result.error,
            )
            self.db.add(msg)
        else:
            msg.body = message
            msg.delivery_status = delivery_status
            msg.zalo_message_id = result.msg_id
            msg.external_error = None if result.ok else result.error
        owner = _normalize_lock_owner(lock_owner)
        if owner is None:
            conv.bot_locked_until = None
            conv.bot_lock_owner = None
            conv.bot_lock_heartbeat_at = None
        else:
            clear_res = await self.db.execute(
                update(Conversation)
                .where(Conversation.id == conv.id, Conversation.bot_lock_owner == owner)
                .values(
                    bot_locked_until=None,
                    bot_lock_owner=None,
                    bot_lock_heartbeat_at=None,
                )
                .execution_options(synchronize_session=False)
            )
            if clear_res.rowcount == 1:
                conv.bot_locked_until = None
                conv.bot_lock_owner = None
                conv.bot_lock_heartbeat_at = None
        if result.ok:
            conv.last_outbound_at = utcnow()
            conv.last_followup_at = utcnow()
            conv.followup_count = (conv.followup_count or 0) + 1
            conv.version += 1
            conv.conversation_seq += 1
        else:
            conv.last_followup_attempt_at = utcnow()
        if outbox_channel is not None and outbox_payload is not None and msg.id is not None:
            from app.models.outbox import OutboxStatus
            from app.services.outbox_service import enqueue_outbox

            outbox = await enqueue_outbox(
                self.db,
                message_id=msg.id,
                channel=outbox_channel,
                payload=outbox_payload,
                status=OutboxStatus.SENT if result.ok else OutboxStatus.FAILED,
                zalo_message_id=result.msg_id,
                last_error=None if result.ok else result.error,
            )
            if outbox is not None:
                msg._delivery_attempts = outbox.attempts
        await self.db.commit()
        await self.db.refresh(msg)
        await self.events.message_created(msg, conv)
        await self.events.conversation_updated(conv)
        return msg

    async def prepare_proactive_message(
        self,
        conv: Conversation,
        *,
        body: str,
        channel: str,
        payload: dict,
    ) -> Message:
        """Commit a proactive BOT message and command before provider I/O."""
        from app.services.outbox_service import create_pending_outbox

        msg = Message(
            conversation_id=conv.id,
            sender=MessageSender.BOT,
            body=body,
            delivery_status=DeliveryStatus.PENDING,
        )
        self.db.add(msg)
        await self.db.flush()
        await create_pending_outbox(
            self.db,
            message_id=msg.id,
            channel=channel,
            payload=payload,
        )
        await self.db.commit()
        await self.db.refresh(msg)
        msg._delivery_attempts = 0
        await self.events.message_created(msg, conv)
        return msg

    # --- recruiter-side state transitions ---
    async def take_over(self, conv: Conversation, recruiter: User) -> Conversation:
        """Atomically claim a conversation. Uses conditional UPDATE so two recruiters
        racing on the same unassigned conversation produce exactly one winner and one
        ConversationConflict (mirrors acquire_lock pattern)."""
        now = utcnow()
        res = await self.db.execute(
            update(Conversation)
            .where(
                Conversation.id == conv.id,
                or_(
                    Conversation.assigned_recruiter_id.is_(None),
                    Conversation.assigned_recruiter_id == recruiter.id,
                ),
            )
            .values(
                mode=ConversationMode.HUMAN,
                status=ConversationStatus.OPEN,
                assigned_recruiter_id=recruiter.id,
                taken_over_at=now,
                needs_human=False,
                unread_count=0,
                bot_locked_until=None,
                bot_lock_owner=None,
                bot_lock_heartbeat_at=None,
                version=Conversation.version + 1,
                conversation_seq=Conversation.conversation_seq + 1,
            )
            .execution_options(synchronize_session=False)
        )
        await self.db.commit()
        if res.rowcount == 0:
            await self.db.refresh(conv)
            raise ConversationConflict(
                "conversation is owned by another recruiter",
                owner_name=await _fetch_owner_name(self.db, conv),
            )
        await self.db.refresh(conv)
        self.db.add(
            Message(
                conversation_id=conv.id,
                sender=MessageSender.SYSTEM,
                body=f"{recruiter.full_name or 'Nhân viên'} đã tiếp nhận hội thoại.",
            )
        )
        await record_audit(
            self.db,
            action="take_over_conversation",
            actor_id=recruiter.id,
            target_type="conversation",
            target_id=str(conv.id),
            payload={"version": conv.version},
        )
        await self.db.commit()
        await self.db.refresh(conv)
        await self.events.conversation_updated(conv)
        return conv

    async def release(self, conv: Conversation, actor: User) -> Conversation:
        conditions = [Conversation.id == conv.id]
        if actor.role != Role.admin:
            conditions.append(
                or_(
                    Conversation.assigned_recruiter_id == actor.id,
                    and_(
                        Conversation.assigned_recruiter_id.is_(None),
                        Conversation.needs_human.is_(False),
                    ),
                )
            )
        released = await self.db.execute(
            update(Conversation)
            .where(*conditions)
            .values(
                mode=ConversationMode.BOT,
                assigned_recruiter_id=None,
                taken_over_at=None,
                needs_human=False,
                bot_locked_until=None,
                bot_lock_owner=None,
                bot_lock_heartbeat_at=None,
                version=Conversation.version + 1,
                conversation_seq=Conversation.conversation_seq + 1,
            )
            .execution_options(synchronize_session=False)
        )
        if released.rowcount == 0:
            await self.db.rollback()
            await self.db.refresh(conv)
            owner_name = (
                await _fetch_owner_name(self.db, conv)
                if conv.assigned_recruiter_id is not None
                else None
            )
            raise ConversationConflict(
                "conversation must be claimed before release",
                owner_name=owner_name,
            )
        await self.db.refresh(conv)
        self.db.add(
            Message(
                conversation_id=conv.id,
                sender=MessageSender.SYSTEM,
                body="Hội thoại đã được trả lại cho chatbot.",
            )
        )
        await record_audit(
            self.db,
            action="release_to_bot",
            actor_id=actor.id,
            target_type="conversation",
            target_id=str(conv.id),
        )
        await self.db.commit()
        await self.db.refresh(conv)
        await self.events.conversation_updated(conv)
        return conv

    async def semi_auto(self, conv: Conversation, recruiter: User) -> Conversation:
        """Atomically enable semi-auto mode. Same conditional-UPDATE pattern as take_over."""
        now = utcnow()
        res = await self.db.execute(
            update(Conversation)
            .where(
                Conversation.id == conv.id,
                or_(
                    Conversation.assigned_recruiter_id.is_(None),
                    Conversation.assigned_recruiter_id == recruiter.id,
                ),
            )
            .values(
                mode=ConversationMode.SEMI_AUTO,
                status=ConversationStatus.OPEN,
                assigned_recruiter_id=recruiter.id,
                taken_over_at=now,
                needs_human=False,
                unread_count=0,
                bot_locked_until=None,
                bot_lock_owner=None,
                bot_lock_heartbeat_at=None,
                version=Conversation.version + 1,
                conversation_seq=Conversation.conversation_seq + 1,
            )
            .execution_options(synchronize_session=False)
        )
        await self.db.commit()
        if res.rowcount == 0:
            await self.db.refresh(conv)
            raise ConversationConflict(
                "conversation is owned by another recruiter",
                owner_name=await _fetch_owner_name(self.db, conv),
            )
        await self.db.refresh(conv)
        self.db.add(
            Message(
                conversation_id=conv.id,
                sender=MessageSender.SYSTEM,
                body=(
                    f"{recruiter.full_name or 'Nhân viên'} đã bật chế độ bán tự động. "
                    "Chatbot sẽ trả lời nếu nhân viên không hoạt động trong 5 phút."
                ),
            )
        )
        await record_audit(
            self.db,
            action="semi_auto_conversation",
            actor_id=recruiter.id,
            target_type="conversation",
            target_id=str(conv.id),
            payload={"version": conv.version, "inactive_after_seconds": 300},
        )
        await self.db.commit()
        await self.db.refresh(conv)
        await self.events.conversation_updated(conv)
        return conv

    async def close(self, conv: Conversation, actor: User) -> Conversation:
        conv.status = ConversationStatus.CLOSED
        conv.mode = ConversationMode.CLOSED
        conv.version += 1
        conv.conversation_seq += 1
        await record_audit(
            self.db,
            action="close_conversation",
            actor_id=actor.id,
            target_type="conversation",
            target_id=str(conv.id),
        )
        await self.db.commit()
        await self.db.refresh(conv)
        await self.events.conversation_updated(conv)
        return conv

    async def reopen(self, conv: Conversation, actor: User) -> Conversation:
        conv.status = ConversationStatus.OPEN
        conv.mode = ConversationMode.BOT
        conv.version += 1
        conv.conversation_seq += 1
        await record_audit(
            self.db,
            action="reopen_conversation",
            actor_id=actor.id,
            target_type="conversation",
            target_id=str(conv.id),
        )
        await self.db.commit()
        await self.db.refresh(conv)
        await self.events.conversation_updated(conv)
        return conv

    async def clear_history(self, conv: Conversation, actor: User) -> Conversation:
        """Hard-delete all messages + bot_runs and reset the conversation shell.

        The conversation row and its linked Lead are KEPT (zalo_chat_id identity
        preserved for inbound routing). Irreversible; admin-only at the router.
        """
        await self.db.execute(
            text("DELETE FROM messages WHERE conversation_id = :cid"), {"cid": conv.id}
        )
        await self.db.execute(
            text("DELETE FROM bot_runs WHERE conversation_id = :cid"), {"cid": conv.id}
        )
        conv.mode = ConversationMode.BOT
        conv.status = ConversationStatus.OPEN
        conv.needs_human = False
        conv.bot_locked_until = None
        conv.bot_lock_owner = None
        conv.bot_lock_heartbeat_at = None
        conv.taken_over_at = None
        conv.assigned_recruiter_id = None
        conv.unread_count = 0
        conv.last_inbound_at = None
        conv.last_outbound_at = None
        conv.followup_count = 0
        conv.last_followup_at = None
        conv.last_followup_attempt_at = None
        conv.followup_opted_out = False
        conv.project_context_state = ConversationProjectState.EXPLORE
        conv.focused_project_id = None
        conv.version += 1
        conv.conversation_seq += 1
        await record_audit(
            self.db,
            action="clear_conversation_history",
            actor_id=actor.id,
            target_type="conversation",
            target_id=str(conv.id),
            payload={"hard_delete": "messages,bot_runs"},
        )
        await self.db.commit()
        await self.db.refresh(conv)
        await self.events.conversation_updated(conv)
        return conv

    async def delete(self, conv: Conversation, actor: User) -> None:
        """Hard-delete a spam or test conversation while retaining its Lead.

        The database cascades the conversation deletion to messages and bot runs.
        Audit rows store the conversation id as text, so the deletion remains
        traceable after the source row is gone. Admin-only enforcement lives at
        the API boundary.
        """
        await record_audit(
            self.db,
            action="delete_conversation",
            actor_id=actor.id,
            target_type="conversation",
            target_id=str(conv.id),
            payload={"hard_delete": "conversation,messages,bot_runs"},
        )
        await self.db.delete(conv)
        await self.db.commit()

    async def mark_read(self, conv: Conversation) -> Conversation:
        conv.unread_count = 0
        await self.db.commit()
        await self.db.refresh(conv)
        await self.events.conversation_updated(conv)
        return conv

    async def record_recruiter_message(
        self, conv: Conversation, recruiter: User, body: str, result: DeliveryResultPort
    ) -> Message:
        msg = Message(
            conversation_id=conv.id,
            sender=MessageSender.RECRUITER,
            recruiter_id=recruiter.id,
            body=body,
            delivery_status=DeliveryStatus.SENT if result.ok else DeliveryStatus.FAILED,
            zalo_message_id=result.msg_id,
            external_error=None if result.ok else result.error,
        )
        self.db.add(msg)
        if result.ok:
            conv.last_outbound_at = utcnow()
        conv.taken_over_at = utcnow()
        conv.version += 1
        conv.conversation_seq += 1
        await record_audit(
            self.db,
            action="send_recruiter_message",
            actor_id=recruiter.id,
            target_type="conversation",
            target_id=str(conv.id),
            payload={"message_id": None, "delivered": result.ok},
        )
        await self.db.commit()
        await self.db.refresh(msg)
        await self.events.message_created(msg, conv)
        await self.events.conversation_updated(conv)
        return msg

    async def prepare_recruiter_message(
        self,
        conv: Conversation,
        recruiter: User,
        *,
        body: str,
        channel: str,
        payload: dict,
    ) -> tuple[Message, int]:
        """Commit one recruiter message and its PENDING command before sending.

        A retry reuses this message/outbox pair; this method is intentionally
        called only for a new human reply, never for a provider retry.
        """
        from app.services.outbox_service import create_pending_outbox

        msg = Message(
            conversation_id=conv.id,
            sender=MessageSender.RECRUITER,
            recruiter_id=recruiter.id,
            body=body,
            delivery_status=DeliveryStatus.PENDING,
        )
        self.db.add(msg)
        await self.db.flush()
        outbox = await create_pending_outbox(
            self.db,
            message_id=msg.id,
            channel=channel,
            payload=payload,
        )
        conv.taken_over_at = utcnow()
        conv.version += 1
        conv.conversation_seq += 1
        await record_audit(
            self.db,
            action="send_recruiter_message",
            actor_id=recruiter.id,
            target_type="conversation",
            target_id=str(conv.id),
            payload={"message_id": msg.id, "delivered": False},
        )
        await self.db.commit()
        await self.db.refresh(msg)
        msg._delivery_attempts = 0
        await self.events.message_created(msg, conv)
        await self.events.conversation_updated(conv)
        return msg, outbox.id

    async def finalize_recruiter_delivery(
        self,
        conv: Conversation,
        *,
        message_id: int,
        outbox_id: int,
        delivered: bool,
        zalo_message_id: str | None = None,
        external_error: str | None = None,
        error_class: str | None = None,
    ) -> Message:
        """Finalize one persisted recruiter command without creating a bubble."""
        from app.models.outbox import OutboxStatus, OutboundOutbox

        msg = await self.db.get(Message, message_id)
        outbox = await self.db.get(OutboundOutbox, outbox_id)
        if msg is None or msg.conversation_id != conv.id or outbox is None:
            raise RuntimeError("outbound message disappeared before delivery finalization")
        delivery_status = _delivery_status_for_send_error(error_class, ok=delivered)
        if delivery_status is None:
            delivery_status = DeliveryStatus.SENT if delivered else DeliveryStatus.FAILED
        msg.delivery_status = delivery_status
        msg.zalo_message_id = zalo_message_id
        msg.external_error = None if delivered else external_error
        outbox.status = (
            OutboxStatus.SENT.value
            if delivered
            else OutboxStatus.SEND_UNKNOWN.value
            if delivery_status == DeliveryStatus.SEND_UNKNOWN
            else OutboxStatus.FAILED.value
        )
        outbox.zalo_message_id = zalo_message_id
        outbox.last_error = None if delivered else external_error
        outbox.updated_at = utcnow()
        if delivered:
            outbox.sent_at = utcnow()
            conv.last_outbound_at = utcnow()
        await self.db.commit()
        await self.db.refresh(msg)
        msg._delivery_attempts = outbox.attempts
        await self.events.message_created(msg, conv)
        await self.events.conversation_updated(conv)
        return msg

    async def finalize_outbound_dispatch(
        self,
        conv: Conversation,
        *,
        message_id: int,
        outbox_id: int,
        delivered: bool,
        zalo_message_id: str | None = None,
        external_error: str | None = None,
        error_class: str | None = None,
        suppressed: bool = False,
        telemetry: OutboundTelemetry | None = None,
    ) -> Message:
        """Finalize a recovered command for any outbound sender without a new row."""
        from app.models.outbox import OutboxStatus, OutboundOutbox

        msg = await self.db.get(Message, message_id)
        outbox = await self.db.get(OutboundOutbox, outbox_id)
        if msg is None or msg.conversation_id != conv.id or outbox is None:
            raise RuntimeError("outbound message disappeared before dispatch finalization")
        delivery_status = (
            DeliveryStatus.SUPPRESSED
            if suppressed
            else _delivery_status_for_send_error(error_class, ok=delivered)
        )
        if delivery_status is None:
            delivery_status = DeliveryStatus.SENT if delivered else DeliveryStatus.FAILED
        msg.delivery_status = delivery_status
        msg.zalo_message_id = zalo_message_id
        msg.external_error = None if delivered else external_error
        outbox.status = (
            OutboxStatus.SUPPRESSED.value
            if suppressed
            else OutboxStatus.SENT.value
            if delivered
            else OutboxStatus.SEND_UNKNOWN.value
            if delivery_status == DeliveryStatus.SEND_UNKNOWN
            else OutboxStatus.FAILED.value
        )
        outbox.zalo_message_id = zalo_message_id
        outbox.last_error = None if delivered else external_error
        outbox.updated_at = utcnow()
        if delivered:
            outbox.sent_at = utcnow()
            conv.last_outbound_at = utcnow()
        if msg.sender == MessageSender.BOT:
            if telemetry is not None:
                telemetry_timings = telemetry.to_stage_timings()
                if msg.bot_run_id is not None:
                    run = await self.db.get(BotRun, msg.bot_run_id)
                    if run is not None:
                        merged_timings = dict(run.stage_timings or {})
                        merged_timings.update(telemetry_timings)
                        run.stage_timings = merged_timings
                else:
                    run = BotRun(
                        conversation_id=conv.id,
                        started_at=msg.created_at or utcnow(),
                        ended_at=utcnow(),
                        version_at_start=int(conv.version),
                        outcome=BotRunOutcome.SENT if delivered else BotRunOutcome.ERROR,
                        stage_timings={
                            "execution_source": "outbox_recovery",
                            "lane": "outbox_recovery",
                            **telemetry_timings,
                        },
                        decision_trace={
                            "version": 1,
                            "events": [
                                {
                                    "seq": 1,
                                    "kind": "decision",
                                    "code": "recovery_reason",
                                    "summary_code": "outbox_recovery",
                                }
                            ],
                            "truncated": False,
                        },
                    )
                    self.db.add(run)
                    await self.db.flush()
                    msg.bot_run_id = run.id
            # A stale-outbox finalization can run on the recovery sweep LONG
            # after the message's own turn ended (it fires only once the outbox
            # row exceeds ``chat_turn_job_timeout`` without a receipt). By then a
            # NEWER turn may already hold this conversation's lock — and clearing
            # it unconditionally here steals that live lock, causing the in-flight
            # turn's ``claim_send`` to suppress (the "Đã chặn" / SUPPRESSED bug).
            # Only clear a lock that is NOT live: one with no owner or whose TTL
            # already expired. A still-live lock belongs to a concurrent turn and
            # is left for its own ``record_bot_outcome`` / the reconciler's TTL
            # sweep. Conditional SQL (evaluated server-side at commit) mirrors the
            # owner-guarded pattern in ``release_lock`` / ``record_bot_outcome``.
            clear_lock = await self.db.execute(
                update(Conversation)
                .where(
                    Conversation.id == conv.id,
                    or_(
                        Conversation.bot_lock_owner.is_(None),
                        Conversation.bot_locked_until.is_(None),
                        Conversation.bot_locked_until <= utcnow(),
                    ),
                )
                .values(
                    bot_locked_until=None,
                    bot_lock_owner=None,
                    bot_lock_heartbeat_at=None,
                )
                .execution_options(synchronize_session=False)
            )
            if clear_lock.rowcount == 1:
                conv.bot_locked_until = None
                conv.bot_lock_owner = None
                conv.bot_lock_heartbeat_at = None
        await self.db.commit()
        await self.db.refresh(msg)
        msg._delivery_attempts = outbox.attempts
        await self.events.message_created(msg, conv)
        await self.events.conversation_updated(conv)
        return msg

    async def retry_recruiter_message(self, conv: Conversation, *, message_id: int) -> int | None:
        """Make an existing definite failure dispatchable again, without a new message."""
        from app.models.outbox import OutboxStatus, OutboundOutbox

        msg = await self.db.get(Message, message_id)
        if (
            msg is None
            or msg.conversation_id != conv.id
            or msg.sender != MessageSender.RECRUITER
            or msg.delivery_status != DeliveryStatus.FAILED
        ):
            return None
        outbox = await self.db.scalar(
            select(OutboundOutbox).where(OutboundOutbox.message_id == message_id)
        )
        if outbox is None or outbox.status != OutboxStatus.FAILED.value:
            return None
        outbox.status = OutboxStatus.PENDING.value
        outbox.last_error = None
        outbox.updated_at = utcnow()
        msg.delivery_status = DeliveryStatus.PENDING
        msg.external_error = None
        await self.db.commit()
        await self.db.refresh(msg)
        msg._delivery_attempts = outbox.attempts
        await self.events.message_created(msg, conv)
        return outbox.id

    # --- OA webhook side events (receipts / lifecycle / interaction signals) ---

    async def apply_delivery_receipt(
        self,
        conv: Conversation,
        *,
        zalo_message_id: str | None,
        delivered: bool = False,
        seen: bool = False,
    ) -> bool:
        """Advance an outbound message's delivery_status from a Zalo receipt.

        Forward-only (READ > DELIVERED > SENT); never regresses and never touches
        ``version`` or ``unread_count`` — a receipt must not invalidate an
        in-flight bot turn's optimistic-lock recheck. Returns whether a row moved.
        """
        moved = await self.apply_delivery_receipt_batch(
            conv,
            zalo_message_ids=[zalo_message_id] if zalo_message_id else [],
            delivered=delivered,
            seen=seen,
        )
        return moved > 0

    async def apply_delivery_receipt_batch(
        self,
        conv: Conversation,
        *,
        zalo_message_ids: list[str],
        delivered: bool = False,
        seen: bool = False,
    ) -> int:
        """Advance delivery_status for multiple outbound messages in one pass.

        ``user_seen_message`` carries an array of message ids (a user can see
        several messages at once); this advances every matched Message row with a
        single commit + a single realtime emit. Forward-only, no ``version`` or
        ``unread_count`` touch (see :meth:`apply_delivery_receipt`). Returns the
        number of rows that moved.

        SEND_UNKNOWN fallback: a message stamped SEND_UNKNOWN (transport timeout,
        stale SENDING, interrupted dispatch) carries NO ``zalo_message_id`` — the
        send failed before Zalo returned one. It therefore can never be matched by
        the ``zalo_message_id IN (ids)`` query above, so a later ``user_seen``
        receipt proving the user actually saw it leaves the row stuck at
        SEND_UNKNOWN forever (recruiter console shows "Chưa xác nhận gửi" despite
        confirmed delivery). A Zalo receipt only fires for a message that exists
        on Zalo's side, so its arrival is ground-truth proof the SEND_UNKNOWN row
        reached Zalo. Advance any id-less SEND_UNKNOWN outbound row in this
        conversation to the target status. Strictly scoped to SEND_UNKNOWN so a
        PENDING placeholder, a known FAILED, or a SUPPRESSED row is never revived.

        Each moved message emits ``message_created`` (in addition to the single
        ``conversation_updated``) so the recruiter console's per-message delivery
        badge refreshes in realtime — the frontend message store updates
        ``delivery_status`` only via ``message.created`` events.
        """
        ids = [mid for mid in zalo_message_ids if mid]
        if not ids:
            return 0
        if seen:
            target = DeliveryStatus.READ
        elif delivered:
            target = DeliveryStatus.DELIVERED
        else:
            return 0
        result = await self.db.scalars(
            select(Message).where(
                Message.conversation_id == conv.id,
                Message.zalo_message_id.in_(ids),
                Message.sender.in_([MessageSender.BOT, MessageSender.RECRUITER]),
            )
        )
        moved: list[Message] = []
        for msg in result.all():
            if receipt_advances(msg.delivery_status, target):
                msg.delivery_status = target
                moved.append(msg)
        if receipt_advances(DeliveryStatus.SEND_UNKNOWN, target):
            # Id-less SEND_UNKNOWN rows can never match the query above. They are
            # disjoint from the id-matched set (a row cannot have both a non-null
            # id-in-ids and a NULL id), so no message is double-counted here.
            unresolved = await self.db.scalars(
                select(Message).where(
                    Message.conversation_id == conv.id,
                    Message.zalo_message_id.is_(None),
                    Message.delivery_status == DeliveryStatus.SEND_UNKNOWN,
                    Message.sender.in_([MessageSender.BOT, MessageSender.RECRUITER]),
                )
            )
            for msg in unresolved.all():
                msg.delivery_status = target
                moved.append(msg)
        if moved:
            await self.db.commit()
            for msg in moved:
                await self.events.message_created(msg, conv)
            await self.events.conversation_updated(conv)
        return len(moved)

    async def record_system_note(self, conv: Conversation, *, body: str) -> Message:
        """Persist an informational SYSTEM message (button click, follow/unfollow).

        Does not bump ``unread_count`` or stamp ``last_inbound_at`` — it is CRM
        chrome, not an inbound worker message, and must not start a bot turn.
        """
        msg = Message(
            conversation_id=conv.id,
            sender=MessageSender.SYSTEM,
            body=body,
        )
        self.db.add(msg)
        await self.db.commit()
        await self.db.refresh(msg)
        await self.events.message_created(msg, conv)
        await self.events.conversation_updated(conv)
        return msg

    async def apply_follow(self, conv: Conversation) -> Conversation:
        """A user followed/returned to the OA: reopen if closed, clear needs_human.

        No ``version`` bump — follow is a CRM-visible refresh, not a takeover, and
        must not suppress an in-flight bot turn.
        """
        if conv.status == ConversationStatus.CLOSED:
            conv.status = ConversationStatus.OPEN
        conv.needs_human = False
        await self.db.commit()
        await self.db.refresh(conv)
        await self.events.conversation_updated(conv)
        return conv

    async def apply_unfollow(self, conv: Conversation) -> Conversation:
        """A user unfollowed the OA: stop proactive follow-up and flag a recruiter.

        Sets ``followup_opted_out`` (the reconcile/proactive worker stops pestering
        a departed user) and ``needs_human``. No mode/status change — closing is a
        recruiter decision, not an automatic one.
        """
        conv.followup_opted_out = True
        conv.needs_human = True
        await self.db.commit()
        await self.db.refresh(conv)
        await self.events.conversation_updated(conv)
        return conv
