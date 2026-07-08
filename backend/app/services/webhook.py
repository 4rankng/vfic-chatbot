"""ZaloWebhookService — the SYNCHRONOUS webhook handler (must ack < 1s).

Flow:
  normalize -> dedup -> ensure conversation -> record_inbound -> run_start_guard
  -> acquire_lock -> send typing indicator -> enqueue RQ job

A Zalo typing indicator is fired from the webhook handler (fire-and-forget) so
the user sees immediate feedback. The RQ worker's _typing_heartbeat keeps it
alive during LLM generation.
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

from app.services.conversation import ConversationService
from app.services.dedup import MessageDedupService
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
    ) -> dict:
        """Run the synchronous guard chain and (if allowed) enqueue the bot turn.

        For the OA channel, only text messages enter the bot-turn queue; receipts,
        follow/unfollow, button clicks, and media/reaction events are routed to
        ``handle_oa_side_event`` instead. The *enqueue* callback returns ``False``
        when the job cannot be enqueued (Redis down / queue depth exceeded); the
        caller translates that to HTTP 503 so Zalo retries.
        """
        if channel == "oa":
            event = parse_oa_webhook_event(payload)
            if event is None:
                return {"status": "ignored"}
            if event.can_start_bot_turn:
                norm = _normalized_from_oa_event(event)
            else:
                return await handle_oa_side_event(db, event)
        else:
            norm = ZaloWebhookService.normalize_bot(payload)
            if norm is None:
                return {"status": "ignored"}

        if not await MessageDedupService.claim(db, norm.zalo_chat_id, norm.msg_hash):
            return {"status": "duplicate"}

        svc = ConversationService(db)
        conv = await svc.ensure(norm.zalo_chat_id, zalo_channel=norm.zalo_channel)
        await db.refresh(conv)
        await svc.record_inbound(
            conv,
            body=norm.user_text,
            zalo_message_id=norm.msg_id,
        )  # persists candidate message; stamps last_inbound_at; bumps unread if HUMAN

        # reload to read committed mode/version
        conv = await svc.get(conv.id)

        if not svc.run_start_guard(conv):  # HUMAN/active SEMI_AUTO/CLOSED -> starve the bot
            return {"status": "starved_human_mode", "conversation_id": str(conv.id)}

        version_at_start = conv.version
        if not await svc.acquire_lock(conv.id):  # another run holds the per-chat mutex
            return {"status": "locked", "conversation_id": str(conv.id)}

        # Fire-and-forget typing indicator so the user sees immediate feedback
        # while the RQ worker picks up the job. The worker's _typing_heartbeat
        # will keep the indicator alive during LLM generation.
        if norm.zalo_channel == "bot":
            asyncio.create_task(_fire_typing(norm.zalo_chat_id))

        job = {
            "conversation_id": str(conv.id),
            "version_at_start": version_at_start,
            "user_text": norm.user_text,
            "user_name": norm.user_name,
            "received_at": datetime.now(timezone.utc).isoformat(),
            # Epoch anchor (not monotonic) so the RQ worker can compute remaining
            # wall-clock budget across the process boundary. See BotRunState.
            "received_at_epoch": time.time(),
        }
        result = enqueue(job)
        if asyncio.iscoroutine(result):
            result = await result
        if result is False:
            await svc.release_lock(conv)  # no worker will clear it
            return {"status": "enqueue_failed", "conversation_id": str(conv.id)}
        return {"status": "queued", "conversation_id": str(conv.id)}


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


async def handle_oa_side_event(db: AsyncSession, event) -> dict:
    """Dispatch non-text OA events: receipts, follow/unfollow, clicks, media.

    None of these start a bot turn, acquire the per-chat lock, or fire typing.
    Receipts advance outbound ``Message.delivery_status``; follow/unfollow adjust
    lifecycle flags; button clicks record a SYSTEM note; media/reactions are
    logged and dropped (deliberately low-noise).
    """
    kind = event.kind
    svc = ConversationService(db)

    if kind in ("user_seen", "user_received"):
        if not event.message_id or not event.sender_id:
            return {"status": "ignored"}
        conv = await svc.ensure(event.scoped_chat_id, zalo_channel="oa")
        await svc.apply_delivery_receipt(
            conv,
            zalo_message_id=event.message_id,
            delivered=(kind == "user_received"),
            seen=(kind == "user_seen"),
        )
        return {"status": "receipt"}

    if kind == "follow":
        conv = await svc.ensure(event.scoped_chat_id, zalo_channel="oa")
        await svc.apply_follow(conv)
        return {"status": "follow"}

    if kind == "unfollow":
        conv = await svc.ensure(event.scoped_chat_id, zalo_channel="oa")
        await svc.apply_unfollow(conv)
        await svc.record_system_note(
            conv, body="Người dùng đã bỏ quan tâm (unfollow) OA."
        )
        return {"status": "unfollow"}

    if kind == "click_to_message":
        conv = await svc.ensure(event.scoped_chat_id, zalo_channel="oa")
        title = _event_button_title(event.raw)
        body = (
            f"👤 Người dùng đã nhấn nút: {title}" if title else "👤 Người dùng đã nhấn nút."
        )
        await svc.record_system_note(conv, body=body)
        return {"status": "button_click"}

    # incoming_media / reaction / oa_sent / oa_sent_anonymous / unknown
    logger.info("oa side event ignored: kind=%s sender=%s", kind, event.sender_id)
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


async def _fire_typing(chat_id: str) -> None:
    """Fire-and-forget Zalo typing indicator from the webhook process.

    Uses a one-shot httpx call to avoid importing the heavy ZaloBotSender class
    into the webhook hot path. Errors are logged but never propagate.
    """
    try:
        import httpx

        from app.core.config import get_settings

        s = get_settings()
        token = s.zalo_bot_token
        if not token:
            return
        base = s.zalo_bot_api_base.rstrip("/")
        async with httpx.AsyncClient(timeout=3) as client:
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
