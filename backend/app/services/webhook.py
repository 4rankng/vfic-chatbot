"""ZaloWebhookService — the SYNCHRONOUS webhook handler (must ack < 1s).

Flow:
  normalize -> dedup -> ensure conversation -> record inbound
  -> run_start_guard -> acquire_lock -> enqueue turn

The tracked worker bridge owns native Zalo Bot status from dependency setup,
then hands it to the turn's heartbeat. Ingress never leaves an unowned provider
request that could outlive the answer. OA has no native typing capability.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import request_id_ctx
from app.models.conversation import ConversationMode
from app.services.conversation import ConversationService
from app.services.dedup import MessageDedupService
from app.services.installation.authority import RuntimeAuthorityStamp
from app.services.zalo_oa_events import parse_oa_webhook_event

logger = logging.getLogger(__name__)

# The guard columns the webhook ack path re-reads after its writes. A full
# ``db.refresh(conv)`` also re-fetches the ``contact`` and ``channel_identity``
# selectin relationships — 3–4 extra SELECTs per refresh, and this path used to
# pay it three times per inbound message on the <1s ack that also stamps
# webhook_ack_ms (runner.py's _OWNERSHIP_REFRESH_COLUMNS carries the same
# measurement for the turn path). Exactly one column-scoped refresh remains,
# immediately before ``run_start_guard`` / ``acquire_lock``. Keep the list
# exhaustive for everything the ack-path guards read (mode/status for
# run_start_guard, taken_over_at/updated_at for the semi-auto branch, version
# for the worker's ownership recheck) or a takeover could slip past a stale
# identity-map snapshot.
_GUARD_REFRESH_COLUMNS = [
    "mode",
    "status",
    "version",
    "taken_over_at",
    "assigned_recruiter_id",
    "updated_at",
    "bot_locked_until",
    "bot_lock_owner",
]


@dataclass
class NormalizedMessage:
    zalo_chat_id: str
    zalo_channel: str
    user_text: str
    user_name: str
    msg_id: str
    msg_hash: str


class ZaloWebhookService:
    @staticmethod
    def normalize_bot(payload: dict) -> NormalizedMessage | None:
        """Extract a text message from a Zalo Bot Platform receive event.
        Returns None if not a processable text message.

        Bot Platform payload (Telegram-style):
          {"update_id": ..., "message": {"message_id": ..., "date": ...,
            "chat": {"id": "<chat_id>", ...}, "from": {"id": ..., "name": ...},
            "text": "..."}}
        ``chat.id`` is the conversation id (a.k.a. zalo_chat_id).
        """
        if not isinstance(payload, dict):
            return None
        msg = payload.get("message") or {}
        chat = msg.get("chat") or {}
        text_body = msg.get("text")
        chat_id = chat.get("id") or msg.get("chat_id")
        if not text_body or not chat_id:
            return None
        msg_id = str(msg.get("message_id") or f"{chat_id}:{str(text_body)[:40]}")
        sender = msg.get("from") or {}
        return NormalizedMessage(
            zalo_chat_id=str(chat_id),
            zalo_channel="bot",
            user_text=str(text_body),
            user_name=str(sender.get("display_name") or sender.get("name") or ""),
            msg_id=msg_id,
            msg_hash=hashlib.sha256(msg_id.encode("utf-8")).hexdigest()[:32],
        )

    @staticmethod
    def normalize_oa(payload: dict) -> NormalizedMessage | None:
        """Extract a text message from a Zalo Official Account webhook event."""
        event = parse_oa_webhook_event(payload)
        if event is None or not event.can_start_bot_turn:
            return None
        return _normalized_from_oa_event(event)

    @staticmethod
    def normalize(payload: dict) -> NormalizedMessage | None:
        return ZaloWebhookService.normalize_bot(payload)

    @staticmethod
    async def handle(
        db: AsyncSession,
        payload: dict,
        *,
        enqueue: Callable[[dict], bool | Awaitable[bool]],
        channel: str = "bot",
        bot_token: str | None = None,
        runtime_authority: RuntimeAuthorityStamp | None = None,
        enrich_oa_profile: Callable[[dict], object] | None = None,
        account_key: str | None = None,
    ) -> dict:
        """Run the synchronous guard chain and (if allowed) enqueue the bot turn.

        For the OA channel, only text messages enqueue bot turns; receipts,
        follow/unfollow, button clicks, and media/reaction events are routed to
        ``handle_oa_side_event`` instead. The *enqueue* callback returns ``False``
        when the job cannot be enqueued (Redis down / queue depth exceeded); the
        caller translates that to HTTP 503 so Zalo retries.

        ``account_key`` is the OA that received the event (multi-OA routing). It
        scopes the contact identity, the conversation, and the OA profile
        enrichment; ``None`` keeps the seeded default OA.
        """
        if channel == "oa":
            event = parse_oa_webhook_event(payload)
            if event is None:
                return {"status": "ignored"}
            if event.can_start_bot_turn:
                norm = _normalized_from_oa_event(event, account_key)
            else:
                return await handle_oa_side_event(db, event, account_key=account_key)
        else:
            event = None
            norm = ZaloWebhookService.normalize_bot(payload)
            if norm is None:
                return {"status": "ignored"}

        if not await MessageDedupService.claim(db, norm.zalo_chat_id, norm.msg_hash):
            return {"status": "duplicate"}

        # ``state`` owns the conversation lifecycle (create-or-fetch, inbound
        # persistence, the takeover guard and the per-chat mutex); ``repo`` owns
        # the reads. Naming the part keeps the guard chain below readable
        # against the state machine it actually consults.
        svc = ConversationService(db)
        state = svc.state
        repo = svc.repo
        conv = await state.ensure(
            norm.zalo_chat_id, zalo_channel=norm.zalo_channel, account_key=account_key
        )
        await state.record_inbound(
            conv,
            body=norm.user_text,
            zalo_message_id=norm.msg_id,
            runtime_revision_id=(runtime_authority.revision_id if runtime_authority else None),
            authority_generation=(
                runtime_authority.authority_generation if runtime_authority else None
            ),
            runtime_fingerprint=(runtime_authority.fingerprint if runtime_authority else None),
        )  # persists candidate message; stamps last_inbound_at; bumps unread if HUMAN

        # The guard chain below runs against ONE column-scoped reload placed
        # immediately before it (see the refresh above ``run_start_guard``).
        # The HUMAN check here reads the row ``ensure`` loaded: it is a cheap
        # short-circuit for the deterministic-profile block, not a takeover
        # guard — a recruiter who flipped the mode mid-flight is caught by the
        # authoritative reload further down.
        if conv.mode == ConversationMode.HUMAN:
            return {"status": "starved_human_mode", "conversation_id": str(conv.id)}

        # A channel redelivery of an inbound that already has a delivered answer
        # must not produce a second turn: `record_inbound` above is idempotent on
        # the provider id, so the redelivery persists nothing and used to fall
        # straight through to the enqueue below — the candidate got the same reply
        # twice (production 2026-10-05, 35 s apart). A redelivery of a message
        # whose first attempt died before answering finds no terminal reply here
        # and still gets its turn, which is why this check is on the answer and
        # not on "did we insert".
        if norm.msg_id and await repo.inbound_is_answered(conv, provider_message_id=norm.msg_id):
            logger.info(
                "duplicate inbound already answered conversation=%s", conv.id
            )
            return {"status": "already_answered", "conversation_id": str(conv.id)}

        # An explicit introduction ("mình tên …") is deterministic data, not
        # something that should wait behind the best-effort LLM extraction job.
        # The later job still enriches the rest of the candidate profile.
        #
        # The employee-support OA is skipped entirely: its writers are staff
        # asking for a password reset, not candidates, so nothing about them
        # belongs in the CRM profile.
        from app.channels.types import TINGTING_OA_ACCOUNT_KEY

        if (account_key or "") != TINGTING_OA_ACCOUNT_KEY:
            try:
                from app.services.candidate_extraction import CandidateExtractionService

                # A bare reply ("Dũng") to the bot's name request is captured here,
                # immediately at inbound, so the next turn personalises with it
                # instead of reverting to the Zalo profile name. Only look back when
                # the reply is short enough to be a name, to skip a history read on
                # normal-length messages. Best-effort: a history read failure just
                # skips this enhancement (name capture is already best-effort).
                prev_bot_message = None
                if len((norm.user_text or "").strip()) <= 30:
                    try:
                        _recent = await repo.last_messages(conv, limit=5)
                        prev_bot_message = _previous_bot_message(_recent)
                    except Exception:
                        prev_bot_message = None

                await CandidateExtractionService.persist_explicit_name(
                    db,
                    norm.zalo_chat_id,
                    norm.user_text,
                    prev_bot_message=prev_bot_message,
                    conversation=conv,
                )
            except Exception as exc:
                # The inbound message is already durable. Do not turn a CRM-profile
                # write failure into a failed webhook delivery. Error text can carry
                # DB-bound candidate values, so log only the exception class.
                try:
                    await db.rollback()
                except Exception as rollback_exc:
                    logger.error(
                        "explicit candidate name persistence rollback failed error_type=%s",
                        type(rollback_exc).__name__,
                    )
                logger.error(
                    "explicit candidate name persistence failed error_type=%s",
                    type(exc).__name__,
                )

        # One column-scoped reload of the guard columns, taken after the
        # deterministic profile write and immediately before the guard chain
        # and ``acquire_lock``. This is the one that makes the takeover race
        # guard correct: a recruiter who claimed the conversation while the
        # profile write was in flight must be seen by ``run_start_guard`` and by
        # the version the worker re-checks. Reload only
        # ``_GUARD_REFRESH_COLUMNS`` — a full ``db.refresh(conv)`` would also
        # re-fetch the ``contact`` and ``channel_identity`` selectin
        # relationships (3–4 extra SELECTs) on the <1s ack that also stamps
        # webhook_ack_ms.
        await db.refresh(conv, _GUARD_REFRESH_COLUMNS)

        if not state.run_start_guard(conv):  # HUMAN/active SEMI_AUTO/CLOSED -> starve the bot
            return {"status": "starved_human_mode", "conversation_id": str(conv.id)}

        version_at_start = conv.version
        lock_owner = await state.acquire_lock(conv.id)
        if lock_owner is None:  # another run holds the per-chat mutex
            return {"status": "locked", "conversation_id": str(conv.id)}

        job = {
            # v2 payload (Phase 3): no provider tokens cross the process
            # boundary. The worker resolves the Zalo Bot token fresh from DB
            # when it needs to bridge the typing indicator. Legacy queued jobs
            # (v absent / v=1) that still carry zalo_bot_token are tolerated by
            # the worker for the rolling-deploy window.
            "v": 2,
            "conversation_id": str(conv.id),
            "version_at_start": version_at_start,
            "user_text": norm.user_text,
            "user_name": norm.user_name,
            "reply_to_message_id": norm.msg_id,
            "lock_owner": str(lock_owner),
            "execution_source": "queued",
            "received_at": datetime.now(timezone.utc).isoformat(),
            # Epoch anchor (not monotonic) so the RQ worker can compute remaining
            # wall-clock budget across the process boundary. See BotRunState.
            "received_at_epoch": time.time(),
            # End-to-end trace id: the webhook's request_id, propagated through
            # RQ → BotRunState → BotRun.trace_id so one query returns every log
            # line for a single candidate message's journey. Contextvar does not
            # cross processes, so the worker re-stashes it from this field.
            "trace_id": request_id_ctx.get(),
            # Carried so the worker can re-fire the Bot typing indicator on
            # pickup. No-op for OA. NOT a secret — just a chat id. The live
            # DB-resolved token is resolved worker-side (no token in payload).
            "zalo_chat_id": norm.zalo_chat_id,
            "zalo_channel": norm.zalo_channel,
            "runtime_revision_id": (
                str(runtime_authority.revision_id) if runtime_authority is not None else ""
            ),
            "authority_generation": (
                runtime_authority.authority_generation if runtime_authority is not None else None
            ),
            "runtime_fingerprint": (
                runtime_authority.fingerprint if runtime_authority is not None else ""
            ),
        }
        result = enqueue(job)
        if asyncio.iscoroutine(result):
            result = await result
        if result is False:
            await state.release_lock(conv, lock_owner=lock_owner)  # no worker will clear it
            return {"status": "start_failed", "conversation_id": str(conv.id)}

        # Best-effort OA profile (avatar/name) enrichment. Fire-and-forget on the
        # low-priority queue; never blocks the webhook ack. Only the external OA
        # user id is carried — the worker resolves live credentials and short-
        # circuits when the lead already has an avatar (no unbounded Zalo calls).
        if (
            channel == "oa"
            and event is not None
            and event.sender_id
            and enrich_oa_profile is not None
        ):
            try:
                enrich_oa_profile(
                    {
                        "zalo_id": norm.zalo_chat_id,
                        "user_id": event.sender_id,
                        "account_key": account_key or "",
                    }
                )
            except Exception:  # noqa: BLE001 — enrichment is best-effort
                logger.debug(
                    "oa profile enrichment enqueue failed chat=%s",
                    norm.zalo_chat_id,
                    exc_info=True,
                )
        return {"status": "processing", "conversation_id": str(conv.id)}


def _normalized_from_oa_event(event, account_key: str | None = None) -> NormalizedMessage:
    """Build a NormalizedMessage from a bot-turn-eligible OA event.

    ``account_key`` scopes the conversation alias to the receiving OA, so the
    same person's thread on another OA of ours stays a separate conversation.
    """
    chat_id = event.scoped_chat_id_for(account_key)
    return NormalizedMessage(
        zalo_chat_id=chat_id,
        zalo_channel="oa",
        user_text=event.text,
        user_name=_oa_sender_name(event.raw),
        msg_id=event.message_id or f"{chat_id}:{event.text[:40]}",
        msg_hash=event.dedup_hash,
    )


async def handle_oa_side_event(db: AsyncSession, event, *, account_key: str | None = None) -> dict:
    """Dispatch non-text OA events: receipts, follow/unfollow, clicks, media.

    None of these start a bot turn, acquire the per-chat lock, or fire typing.
    Receipts advance outbound ``Message.delivery_status``; follow/unfollow adjust
    lifecycle flags; button clicks record a SYSTEM note; media/reactions are
    logged and dropped (deliberately low-noise).

    ``account_key`` scopes every conversation lookup to the OA that received the
    event, so a receipt on one OA can never advance another OA's message.
    """
    kind = event.kind
    # Receipts, follow/unfollow and notes are all conversation-state transitions.
    state = ConversationService(db).state

    if kind in ("user_seen", "user_received"):
        if not event.message_ids or not event.sender_id:
            return {"status": "ignored"}
        conv = await state.ensure(
            event.scoped_chat_id_for(account_key),
            zalo_channel="oa",
            account_key=account_key,
        )
        await state.apply_delivery_receipt_batch(
            conv,
            zalo_message_ids=list(event.message_ids),
            delivered=(kind == "user_received"),
            seen=(kind == "user_seen"),
        )
        return {"status": "receipt"}

    if kind == "follow":
        conv = await state.ensure(
            event.scoped_chat_id_for(account_key),
            zalo_channel="oa",
            account_key=account_key,
        )
        await state.apply_follow(conv)
        return {"status": "follow"}

    if kind == "unfollow":
        conv = await state.ensure(
            event.scoped_chat_id_for(account_key),
            zalo_channel="oa",
            account_key=account_key,
        )
        await state.apply_unfollow(conv)
        await state.record_system_note(conv, body="Người dùng đã bỏ quan tâm (unfollow) OA.")
        return {"status": "unfollow"}

    if kind == "click_to_message":
        conv = await state.ensure(
            event.scoped_chat_id_for(account_key),
            zalo_channel="oa",
            account_key=account_key,
        )
        title = _event_button_title(event.raw)
        body = f"👤 Người dùng đã nhấn nút: {title}" if title else "👤 Người dùng đã nhấn nút."
        await state.record_system_note(conv, body=body)
        return {"status": "button_click"}

    # incoming_media / reaction / oa_sent / oa_sent_anonymous / unknown
    logger.info("oa side event ignored: kind=%s", kind)
    return {"status": "ignored"}


def _event_button_title(raw: dict) -> str:
    """Best-effort extraction of a clicked button's label from the raw payload."""
    msg = raw.get("message")
    if isinstance(msg, dict):
        title = msg.get("title") or msg.get("button_title") or msg.get("label")
        if title:
            return str(title)
    for key in ("event", "recipient"):
        nested = raw.get(key)
        if isinstance(nested, dict):
            title = nested.get("title") or nested.get("button_title")
            if title:
                return str(title)
    return ""


async def _fire_typing(chat_id: str, bot_token: str | None = None) -> None:
    """Send one native Zalo status pulse for the tracked turn bridge.

    Uses the process-scoped ``zalo_bot_typing`` httpx client (Tech-Lead Directive
    §4) — a short-timeout connection reused across all typing pulses — rather
    than importing the heavier ``ZaloBotSender`` class into the webhook hot path.
    ``bot_token`` is the DB-resolved live token passed in from the router; it
    falls back to ``settings.zalo_bot_token`` (stale in prod) only when a caller
    omits it. Errors are logged but never propagate.
    """
    try:
        from app.core.config import ZALO_BOT_API_BASE, get_settings
        from app.core.http import get_http_client

        s = get_settings()
        token = bot_token or s.zalo_bot_token
        if not token:
            return
        # NOTE: this previously read ``s.zalo_bot_api_base``, which does not
        # exist on Settings (only the module-level ZALO_BOT_API_BASE constant
        # does) — so the typing indicator silently raised AttributeError and
        # was swallowed by the best-effort except. Using the constant fixes it.
        base = ZALO_BOT_API_BASE.rstrip("/")
        client = await get_http_client(
            "zalo_bot_typing",
            timeout=3,
            settings=s,
        )
        await client.post(
            f"{base}/bot{token}/sendChatAction",
            json={"chat_id": chat_id, "action": "typing"},
        )
    except Exception as exc:  # noqa: BLE001 — typing is best-effort
        logger.debug("native typing request failed error_type=%s", type(exc).__name__)


def _oa_sender_name(payload: dict) -> str:
    sender = payload.get("sender") or payload.get("from") or {}
    if not isinstance(sender, dict):
        return ""
    return str(sender.get("name") or sender.get("display_name") or "")


def _previous_bot_message(messages) -> str | None:
    """The bot turn that immediately preceded this inbound.

    ``ConversationRepository.last_messages`` returns newest-first, so the FIRST
    bot row in the list is the immediate predecessor. Iterating the list in
    reverse selected the oldest bot turn in the window instead, which is how a
    bare name reply ("Bùi thị hòa") missed its own name request — and why the
    deterministic name capture never wrote a name for those turns.
    """
    return next(
        (m.body for m in messages if getattr(m, "sender", None) == "BOT"),
        None,
    )
