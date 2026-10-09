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
from sqlalchemy.exc import IntegrityError
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.channels.types import ZALO_OA_DEFAULT_ACCOUNT_KEY, oa_user_id
from app.conversation_messaging.application.ports import (
    ConversationEventsPort,
)
from app.models.channel_account import ChannelAccount
from app.models.contact import ContactChannelIdentity
from app.models.conversation import (
    Conversation,
    ConversationMode,
    ConversationStatus,
    Message,
    MessageSender,
)
from app.recruitment.domain.proactive_policy import PROACTIVE_OPTOUT_PHRASES
from app.services.audit_service import record_audit
from app.services.conversation._shared import (
    merge_attribution,
    utcnow,
)
from app.services.conversation.bot_outcome import BotOutcomeMixin
from app.services.conversation.locking import LockingMixin
from app.services.conversation.reconcile import ReconcileMixin
from app.services.conversation.send_claim import SendClaimMixin

# SEMI_AUTO: the assigned human owns the thread for this long after their last
# message (``taken_over_at``/``updated_at``); past it, new inbound is answered
# by the bot again. Operator requirement 2026-09-28: 30 minutes (was 5).
_SEMI_AUTO_INACTIVITY = timedelta(minutes=30)

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
        from app.models.contact import Contact, ContactChannelIdentity

        conv = await self.repo.get_by_identity(
            provider=provider, account_key=account_key, external_id=external_id
        )
        if conv is not None:
            # Backfill a missing Zalo alias on an existing row (defensive).
            if zalo_chat_id_alias and not conv.zalo_chat_id:
                conv.zalo_chat_id = zalo_chat_id_alias
            if (
                zalo_channel_alias
                and (not conv.zalo_channel or conv.zalo_channel == "bot")
                and zalo_channel_alias != "bot"
            ):
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
            # A created conversation carries unloaded relationships: the first
            # message's realtime events serialize this instance, and the lazy
            # load of channel_identity outside the async greenlet raised
            # MissingGreenlet, 500ing the webhook AFTER the inbound commit —
            # the first message was durable but never enqueued or answered
            # (2026-09-28 prod). Fetched conversations already carry both
            # relationships via selectin loading; the create path must too.
            await self.db.refresh(conv, ["contact", "channel_identity"])
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
        been inactive for thirty minutes. HUMAN/CLOSED starve the bot. The
        per-account pause switch (``channel_bot_paused``) is checked separately
        because it needs a lookup this sync guard cannot make.
        """
        if conv.mode == ConversationMode.BOT:
            return True
        if conv.mode == ConversationMode.SEMI_AUTO:
            return self.semi_auto_inactive(conv)
        return False

    async def bot_paused(self, conv: Conversation) -> bool:
        """Whether the conversation's channel account has the bot paused.

        Owner request 2026-10-08: a Page-level switch that keeps the connection
        and inbound persistence but stops the bot from answering. Checked at
        every turn entry — inbound scheduling, the reconcile sweep, and the
        run_turn backstop — so a toggle flip cannot race a queued turn into a
        send. A lookup failure answers False (fail-open): an infrastructure
        hiccup must not silently silence the bot.
        """
        identity_id = getattr(conv, "channel_identity_id", None)
        if identity_id is None:
            return False
        try:
            row = (
                await self.db.execute(
                    select(ChannelAccount.bot_paused)
                    .join(
                        ContactChannelIdentity,
                        and_(
                            ContactChannelIdentity.provider == ChannelAccount.provider,
                            ContactChannelIdentity.account_key == ChannelAccount.account_key,
                        ),
                    )
                    .where(
                        ContactChannelIdentity.id == identity_id,
                        ChannelAccount.status == "ACTIVE",
                    )
                )
            ).first()
        except Exception:  # noqa: BLE001 — a guard read must not break the turn path
            logger.warning(
                "bot pause lookup failed identity=%s", identity_id, exc_info=True
            )
            return False
        # SQLAlchemy Row is a tuple subclass; anything else (a stubbed session)
        # reads as "not paused" rather than silencing the bot.
        return isinstance(row, (tuple, list)) and row[0] is True

    async def stamp_attribution(
        self, conv: Conversation, attribution: dict | None
    ) -> None:
        """Fold a source touch that has no message to carry it (best-effort).

        Used by referral-only webhook events (Messenger Get Started / m.me
        postback): there is no inbound row to piggyback the write on, so this
        commits its own transaction. A source hint must never fail the webhook
        ack — every error is logged and rolled back, never raised.
        """
        if not attribution:
            return
        merged = merge_attribution(conv.attribution, attribution)
        if merged == (conv.attribution or {}):
            return
        conv.attribution = merged
        try:
            await self.db.commit()
        except Exception:  # noqa: BLE001 — attribution is a hint, never load-bearing
            logger.warning(
                "attribution stamp failed conversation=%s", conv.id, exc_info=True
            )
            try:
                await self.db.rollback()
            except Exception:  # noqa: BLE001 — rollback failure must stay silent too
                logger.debug("attribution stamp rollback failed", exc_info=True)

    async def clear_ad_entry_prefill_flag(
        self,
        conversation_id: uuid.UUID,
    ) -> bool:
        """Clear the ad-prefill skip flag on the candidate's first real message.

        The candidate typing for themselves is what reopens Meta's standard
        24h window, so from this message on the thread rides the normal bot
        path again — including reconcile recovery if that turn later dies.
        Also drops the consecutive-refusal counter so a later window problem
        starts a fresh two-attempt cycle. Best-effort by contract: an unknown
        id or a thread carrying neither key is a no-op that reports False.
        """
        conv = await self.db.get(Conversation, conversation_id)
        attribution = conv.attribution or {} if conv is not None else {}
        if conv is None or not (
            attribution.get("ad_prefill_pending") == "true"
            or "ad_prefill_refusals" in attribution
        ):
            return False
        conv.attribution = {
            key: value
            for key, value in attribution.items()
            if key not in ("ad_prefill_pending", "ad_prefill_refusals")
        }
        await self.db.commit()
        return True

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
        attribution: dict | None = None,
    ) -> Message:
        """Persist an inbound worker message and update conversation attention state.

        ``attribution`` is the source the provider attached to this inbound
        (a Zalo prefill post code, a Messenger referral). It rides the same
        transaction as the message and is folded into the conversation's
        first-touch record by :func:`merge_attribution` — first touch wins,
        later touches only fill gaps.

        ``provider_message_id`` is the canonical neutral message id (Alembic
        0047). ``zalo_message_id`` remains as a compatibility alias; when only
        ``zalo_message_id`` is supplied, it is copied to ``provider_message_id``
        so the durable inbound idempotency index applies to Zalo rows too.

        Idempotent on ``(conversation_id, provider_message_id)``: a redelivery
        whose dedup row has expired returns the already-durable row instead of
        raising, so the caller continues toward lock+enqueue and the redelivery
        recovers a first message whose original attempt died after commit.
        """
        neutral_id = provider_message_id or zalo_message_id
        conv_id = conv.id
        if neutral_id is not None:
            # Durable idempotency (Alembic 0047's partial unique index): the
            # INSERT is a no-op when this inbound already exists, so a Zalo
            # redelivery beyond the 8s dedup window returns the durable row
            # instead of 500ing into an endless retry loop (2026-09-28 prod:
            # a first message whose original attempt committed the inbound
            # and then died before enqueueing stayed unanswered forever).
            # The returned existing row lets the caller continue toward
            # lock+enqueue — the redelivery itself recovers the message in
            # seconds; the per-chat mutex serializes it against any turn the
            # original delivery did manage to enqueue.
            inserted_id = await self.db.scalar(
                pg_insert(Message)
                .values(
                    conversation_id=conv.id,
                    sender=MessageSender.WORKER,
                    body=body,
                    zalo_message_id=zalo_message_id,
                    provider_message_id=neutral_id,
                    runtime_revision_id=runtime_revision_id,
                    authority_generation=authority_generation,
                    runtime_fingerprint=runtime_fingerprint,
                )
                .on_conflict_do_nothing(
                    index_elements=["conversation_id", "provider_message_id"],
                    index_where=Message.provider_message_id.is_not(None),
                )
                .returning(Message.id)
            )
            if inserted_id is None:
                existing = await self.db.scalar(
                    select(Message).where(
                        Message.conversation_id == conv_id,
                        Message.provider_message_id == neutral_id,
                    )
                )
                if existing is None:  # pragma: no cover - defensive
                    raise IntegrityError("duplicate inbound insert vanished", None, None)
                logger.info(
                    "duplicate inbound delivery ignored conversation=%s",
                    conv_id,
                )
                return existing
            msg = await self.db.get(Message, inserted_id)
        else:
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
        if attribution:
            conv.attribution = merge_attribution(conv.attribution, attribution)
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
        await self.db.commit()
        # Post-commit bookkeeping must never fail the webhook: the inbound is
        # durable, so a realtime hiccup loses a UI update, never a message
        # (same contract as schedule_realtime's serialization armor).
        try:
            await self.db.refresh(msg)
            await self.events.message_created(msg, conv)
            await self.events.conversation_updated(conv)
        except Exception:  # noqa: BLE001 — the ack outranks the UI update
            logger.warning(
                "inbound realtime events failed; message is durable conversation=%s",
                conv_id,
                exc_info=True,
            )
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
        the console's suppressed badge). With the flag the transition writes only
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
