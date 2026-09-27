"""ZaloWebhookService — the SYNCHRONOUS webhook handler (must ack < 1s).

Flow:
  normalize -> dedup -> ensure conversation -> record inbound
  -> run_start_guard -> acquire_lock -> typing -> enqueue RQ job

A Zalo typing indicator is fired from the webhook handler (fire-and-forget) so
the user sees immediate feedback. The turn's _status_heartbeat keeps pulsing it
during LLM generation. (The OA channel has no typing endpoint, so on OA the
indicator is a logged no-op — the answer itself landing is the only signal.)
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
                norm = _normalized_from_oa_event(event)
            else:
                return await handle_oa_side_event(db, event, account_key=account_key)
        else:
            event = None
            norm = ZaloWebhookService.normalize_bot(payload)
            if norm is None:
                return {"status": "ignored"}

        if not await MessageDedupService.claim(db, norm.zalo_chat_id, norm.msg_hash):
            return {"status": "duplicate"}

        svc = ConversationService(db)
        conv = await svc.ensure(
            norm.zalo_chat_id, zalo_channel=norm.zalo_channel, account_key=account_key
        )
        await db.refresh(conv)
        await svc.record_inbound(
            conv,
            body=norm.user_text,
            zalo_message_id=norm.msg_id,
            runtime_revision_id=(runtime_authority.revision_id if runtime_authority else None),
            authority_generation=(runtime_authority.authority_generation if runtime_authority else None),
            runtime_fingerprint=(runtime_authority.fingerprint if runtime_authority else None),
        )  # persists candidate message; stamps last_inbound_at; bumps unread if HUMAN

        # Human-only conversations keep every inbound but spend no resources on
        # candidate extraction or chatbot work. A second guard below closes the
        # race where a recruiter takes over during deterministic name capture.
        conv = await svc.get(conv.id)
        await db.refresh(conv)
        if conv.mode == ConversationMode.HUMAN:
            return {"status": "starved_human_mode", "conversation_id": str(conv.id)}

        # An explicit introduction ("mình tên …") is deterministic data, not
        # something that should wait behind the best-effort LLM extraction job.
        # The later job still enriches the rest of the candidate profile.
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
                    _recent = await svc.last_messages(conv, limit=5)
                    prev_bot_message = next(
                        (
                            m.body
                            for m in reversed(_recent)
                            if getattr(m, "sender", None) == "BOT"
                        ),
                        None,
                    )
                except Exception:
                    prev_bot_message = None

            await CandidateExtractionService.persist_explicit_name(
                db,
                norm.zalo_chat_id,
                norm.user_text,
                prev_bot_message=prev_bot_message,
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

        # Reload and recheck because a recruiter may have taken over while the
        # deterministic profile write was in progress.
        conv = await svc.get(conv.id)
        await db.refresh(conv)

        if not svc.run_start_guard(conv):  # HUMAN/active SEMI_AUTO/CLOSED -> starve the bot
            return {"status": "starved_human_mode", "conversation_id": str(conv.id)}

        version_at_start = conv.version
        lock_owner = await svc.acquire_lock(conv.id)
        if lock_owner is None:  # another run holds the per-chat mutex
            return {"status": "locked", "conversation_id": str(conv.id)}

        # Fire-and-forget typing indicator so the user sees immediate feedback
        # while the RQ worker picks up the job. The turn's _status_heartbeat
        # keeps pulsing the indicator during LLM generation (a logged no-op on
        # the OA channel, which has no typing endpoint). The token is the
        # DB-resolved live value (env ZALO_BOT_TOKEN is stale).
        if norm.zalo_channel == "bot":
            asyncio.create_task(_fire_typing(norm.zalo_chat_id, bot_token))

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
            await svc.release_lock(conv, lock_owner=lock_owner)  # no worker will clear it
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


def _normalized_from_oa_event(event) -> NormalizedMessage:
    """Build a NormalizedMessage from a bot-turn-eligible OA event."""
    return NormalizedMessage(
        zalo_chat_id=event.scoped_chat_id,
        zalo_channel="oa",
        user_text=event.text,
        user_name=_oa_sender_name(event.raw),
        msg_id=event.message_id or f"{event.scoped_chat_id}:{event.text[:40]}",
        msg_hash=event.dedup_hash,
    )


async def handle_oa_side_event(
    db: AsyncSession, event, *, account_key: str | None = None
) -> dict:
    """Dispatch non-text OA events: receipts, follow/unfollow, clicks, media.

    None of these start a bot turn, acquire the per-chat lock, or fire typing.
    Receipts advance outbound ``Message.delivery_status``; follow/unfollow adjust
    lifecycle flags; button clicks record a SYSTEM note; media/reactions are
    logged and dropped (deliberately low-noise).

    ``account_key`` scopes every conversation lookup to the OA that received the
    event, so a receipt on one OA can never advance another OA's message.
    """
    kind = event.kind
    svc = ConversationService(db)

    if kind in ("user_seen", "user_received"):
        if not event.message_ids or not event.sender_id:
            return {"status": "ignored"}
        conv = await svc.ensure(
            event.scoped_chat_id, zalo_channel="oa", account_key=account_key
        )
        await svc.apply_delivery_receipt_batch(
            conv,
            zalo_message_ids=list(event.message_ids),
            delivered=(kind == "user_received"),
            seen=(kind == "user_seen"),
        )
        return {"status": "receipt"}

    if kind == "follow":
        conv = await svc.ensure(
            event.scoped_chat_id, zalo_channel="oa", account_key=account_key
        )
        await svc.apply_follow(conv)
        return {"status": "follow"}

    if kind == "unfollow":
        conv = await svc.ensure(
            event.scoped_chat_id, zalo_channel="oa", account_key=account_key
        )
        await svc.apply_unfollow(conv)
        await svc.record_system_note(conv, body="Người dùng đã bỏ quan tâm (unfollow) OA.")
        return {"status": "unfollow"}

    if kind == "click_to_message":
        conv = await svc.ensure(
            event.scoped_chat_id, zalo_channel="oa", account_key=account_key
        )
        title = _event_button_title(event.raw)
        body = f"👤 Người dùng đã nhấn nút: {title}" if title else "👤 Người dùng đã nhấn nút."
        await svc.record_system_note(conv, body=body)
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
    """Fire-and-forget Zalo typing indicator from the webhook process.

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
    except Exception:  # noqa: BLE001 — typing is best-effort
        logger.debug("failed to send typing indicator for %s", chat_id, exc_info=True)


def _oa_sender_name(payload: dict) -> str:
    sender = payload.get("sender") or payload.get("from") or {}
    if not isinstance(sender, dict):
        return ""
    return str(sender.get("name") or sender.get("display_name") or "")
