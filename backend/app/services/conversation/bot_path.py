"""Bot-send path of the conversation state layer.

Owns the part of the bot-send family that stays here: webhook-side conversation
primitives, inbound guards, intent escalation, and proactive follow-up. The four
extracted halves of the former god file are mixed into ``BotConversationState``
below, so each change reason has its own module:

- ``locking.LockingMixin`` — per-chat mutex acquire / release / renew / stale
  recovery (pure model-state logic, no dependency on the send path).
- ``send_claim.SendClaimMixin`` — the TOCTOU send claim and the finalization of
  the durable outbox command.
- ``bot_outcome.BotOutcomeMixin`` — bot_run + BOT message outcome recording.
- ``reconcile.ReconcileMixin`` — the sweeps that resolve rows a crashed turn
  left behind.

Recruiter-facing messaging lives in ``recruiter_path.py``; shared helpers in
``_shared.py``.
"""

from __future__ import annotations

import logging
import uuid
from datetime import timedelta, timezone

from sqlalchemy import and_, select, update

from app.channels.types import ZALO_OA_DEFAULT_ACCOUNT_KEY, oa_user_id
from app.conversation_messaging.application.ports import (
    ConversationEventsPort,
    DeliveryResultPort,
)
from app.conversation_messaging.domain.ownership import (
    normalize_lock_owner as _normalize_lock_owner,
)
from app.models.conversation import (
    Conversation,
    ConversationMode,
    ConversationStatus,
    DeliveryStatus,
    Message,
    MessageSender,
)
from app.recruitment.domain.proactive_policy import PROACTIVE_OPTOUT_PHRASES
from app.services.audit_service import record_audit
from app.services.conversation._shared import utcnow
from app.services.conversation.bot_outcome import BotOutcomeMixin
from app.services.conversation.locking import LockingMixin
from app.services.conversation.reconcile import ReconcileMixin
from app.services.conversation.send_claim import SendClaimMixin

_SEMI_AUTO_INACTIVITY = timedelta(minutes=5)

# The human-visible note an escalation leaves in the transcript, next to the
# handoff reply. Kept as a constant so the deploy smoke gate can assert the
# operator-visible artifact without duplicating the literal.
ESCALATION_SYSTEM_NOTE = "Luồng trích xuất đề nghị nhân viên xác minh ý định liên hệ."

logger = logging.getLogger(__name__)


class BotConversationState(
    LockingMixin,
    SendClaimMixin,
    BotOutcomeMixin,
    ReconcileMixin,
):
    """Mutates conversation/message rows for the bot-send path.

    Bot-send half of the former ``ConversationState``: composes a
    ``ConversationRepository`` (for reads within mutations) and a
    ``ConversationEventBus`` (for publishing). Pure orchestration — no new
    business rules. The lock lifecycle, send claim, outcome recording, and
    reconcile sweeps arrive via their mixins (see the module docstring).
    """

    def __init__(self, db, repo, events: ConversationEventsPort) -> None:
        self.db = db
        self.repo = repo
        self.events = events


    # --- webhook-side primitives (used by US-006 chatbot) ---

    async def ensure(
        self,
        zalo_chat_id: str,
        *,
        zalo_channel: str = "bot",
        account_key: str | None = None,
    ) -> Conversation:
        """Resolve a Zalo channel/chat pair to its canonical channel identity.

        The Zalo account keys are the stable synthetic values backfilled by
        Alembic 0047. OA's ``oa:`` storage prefix is stripped from the external
        id, matching the backfill normalization.

        ``account_key`` selects the receiving OA for ``zalo_channel="oa"``: the
        multi-OA router passes the OA id of the linked account the event came
        from, and everything else (the recruitment Bot, the original OA, any
        caller that omits the key) keeps the seeded default.
        """
        if zalo_channel == "oa":
            provider = "zalo_oa"
            account_key = account_key or ZALO_OA_DEFAULT_ACCOUNT_KEY
            # The alias carries the receiving OA (``oa:<account_key>:<user_id>``
            # for a non-original OA); the identity stores the bare user id.
            external_id = oa_user_id(zalo_chat_id)
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
        preserve_turn_ownership: bool = False,
    ) -> bool:
        """Move an extraction-classified contact to human-only review.

        Candidate extraction runs after the chatbot reply has already been sent.
        This transition therefore controls future turns only. A conditional
        update makes concurrent persistence jobs create one note and audit event,
        while the expected version prevents stale results from overriding a newer
        inbound or recruiter decision.

        ``preserve_turn_ownership`` is for the one caller that runs INSIDE the
        bot turn it is escalating — the support-OA handoff (``lanes``). That
        turn's ``claim_send`` re-checks ``version`` and a live ``bot_lock_owner``
        server-side at commit time, so bumping the version or releasing the lock
        here makes the claim lose and the handoff reply never reaches the
        employee (the reply the employee is waiting for is recorded SUPPRESSED,
        the console's "Đã chặn" badge). With the flag the transition writes only
        ``mode``/``status``/``needs_human`` (+ the monotonic ``conversation_seq``)
        and leaves ``version`` and the ``bot_lock_*`` trio to the owning turn,
        which releases the lock in ``record_bot_outcome`` once the reply is out.
        The claim is not weakened: a takeover or a newer inbound still loses it
        on the lock owner / version check.
        """
        target_state = and_(
            Conversation.mode == ConversationMode.HUMAN,
            Conversation.needs_human.is_(True),
        )
        values: dict = {
            "mode": ConversationMode.HUMAN,
            "status": ConversationStatus.OPEN,
            "needs_human": True,
            "conversation_seq": Conversation.conversation_seq + 1,
        }
        if not preserve_turn_ownership:
            values.update(
                bot_locked_until=None,
                bot_lock_owner=None,
                bot_lock_heartbeat_at=None,
                version=Conversation.version + 1,
            )
        transition = await self.db.execute(
            update(Conversation)
            .where(
                Conversation.id == conv.id,
                Conversation.version == expected_version,
                Conversation.status != ConversationStatus.CLOSED,
                ~target_state,
            )
            .values(**values)
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
            body=ESCALATION_SYSTEM_NOTE,
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
        suppressed = bool(getattr(result, "suppressed", False))
        delivery_status = (
            DeliveryStatus.SUPPRESSED
            if suppressed
            else DeliveryStatus.SENT
            if result.ok
            else DeliveryStatus.FAILED
        )
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
                provider_message_id=result.msg_id,
                external_error=None if result.ok else result.error,
            )
            self.db.add(msg)
        else:
            msg.body = message
            msg.delivery_status = delivery_status
            msg.zalo_message_id = result.msg_id
            msg.provider_message_id = result.msg_id
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
                status=(
                    OutboxStatus.SUPPRESSED
                    if suppressed
                    else OutboxStatus.SENT
                    if result.ok
                    else OutboxStatus.FAILED
                ),
                zalo_message_id=result.msg_id,
                provider_message_id=result.msg_id,
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
