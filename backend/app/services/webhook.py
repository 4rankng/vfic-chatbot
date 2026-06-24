"""ZaloWebhookService — the SYNCHRONOUS webhook handler (must ack < 1s).

Port + ordering of the n8n trigger chain:
  normalize -> dedup(8s) -> ensure conversation -> record_inbound -> run_start_guard
  -> acquire_lock(30s mutex) -> enqueue RQ job

Everything from Typing onward runs on an RQ worker (injectable `enqueue`). No LLM
and no Zalo send happen here.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.conversation_service import ConversationService
from app.services.dedup import MessageDedupService


@dataclass
class NormalizedMessage:
    zalo_chat_id: str
    user_text: str
    user_name: str
    msg_id: str
    msg_hash: str


class ZaloWebhookService:
    @staticmethod
    def normalize(payload: dict) -> NormalizedMessage | None:
        """Extract a text message from a Zalo OA receive event. Returns None if not
        a processable text message."""
        if not isinstance(payload, dict):
            return None
        # Zalo may wrap a batch; handle the single-event object.
        sender = payload.get("sender") or {}
        msg = payload.get("message") or {}
        text_body = msg.get("text")
        chat_id = sender.get("id")
        if not text_body or not chat_id:
            return None
        msg_id = str(msg.get("msg_id") or f"{chat_id}:{str(text_body)[:40]}")
        return NormalizedMessage(
            zalo_chat_id=str(chat_id),
            user_text=str(text_body),
            user_name=str(sender.get("name") or ""),
            msg_id=msg_id,
            msg_hash=hashlib.sha256(msg_id.encode("utf-8")).hexdigest()[:32],
        )

    @staticmethod
    async def handle(
        db: AsyncSession,
        payload: dict,
        *,
        enqueue: Callable[[dict], Awaitable[None] | None],
    ) -> dict:
        """Run the synchronous guard chain and (if allowed) enqueue the bot turn."""
        norm = ZaloWebhookService.normalize(payload)
        if norm is None:
            return {"status": "ignored"}

        if not await MessageDedupService.claim(db, norm.zalo_chat_id, norm.msg_hash):
            return {"status": "duplicate"}

        svc = ConversationService(db)
        conv = await svc.ensure(norm.zalo_chat_id)
        await svc.record_inbound(conv)  # stamps last_inbound_at; bumps unread if HUMAN

        # reload to read committed mode/version
        conv = await svc.get(conv.id)

        if not svc.run_start_guard(conv):  # HUMAN/CLOSED -> starve the bot
            return {"status": "starved_human_mode", "conversation_id": str(conv.id)}

        version_at_start = conv.version
        if not await svc.acquire_lock(conv.id):  # another run holds the per-chat mutex
            return {"status": "locked", "conversation_id": str(conv.id)}

        job = {
            "conversation_id": str(conv.id),
            "version_at_start": version_at_start,
            "user_text": norm.user_text,
            "user_name": norm.user_name,
            "received_at": datetime.now(timezone.utc).isoformat(),
        }
        result = enqueue(job)
        if result is not None:
            await result
        return {"status": "queued", "conversation_id": str(conv.id)}
