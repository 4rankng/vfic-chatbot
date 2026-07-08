"""Zalo Official Account webhook event normalization.

The OA webhook surface reports both user-authored messages and delivery/status
events. Only text messages should enter the chatbot turn queue; everything else
is normalized so callers can log, audit, or route it without losing the raw
Zalo payload.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any, Literal

OAEventKind = Literal[
    "incoming_text",
    "incoming_media",
    "click_to_message",
    "reaction",
    "oa_sent",
    "oa_sent_anonymous",
    "user_received",
    "user_seen",
    "unknown",
]

TEXT_MESSAGE_EVENTS = {"user_send_text", "user_send_text_message"}
MEDIA_MESSAGE_EVENTS = {
    "user_send_image",
    "user_send_sticker",
    "user_send_gif",
    "user_send_audio",
    "user_send_video",
    "user_send_file",
    "user_send_link",
}
CLICK_TO_MESSAGE_EVENTS = {
    "user_click_message",
    "user_click_send_message",
    "user_click_chat_button",
    "user_click_button",
}
REACTION_EVENTS = {"user_reacted_message", "user_react_message"}
USER_RECEIVED_EVENTS = {"user_received_message", "user_receive_message"}
USER_SEEN_EVENTS = {"user_seen_message", "user_viewed_message"}


@dataclass(frozen=True)
class ZaloOAWebhookEvent:
    event_name: str
    kind: OAEventKind
    sender_id: str
    recipient_id: str
    message_id: str
    text: str
    timestamp: str
    raw: dict[str, Any]

    @property
    def scoped_chat_id(self) -> str:
        return f"oa:{self.sender_id}" if self.sender_id else ""

    @property
    def can_start_bot_turn(self) -> bool:
        return self.kind == "incoming_text" and bool(self.sender_id and self.text)

    @property
    def dedup_hash(self) -> str:
        stable_id = self.message_id or f"{self.event_name}:{self.sender_id}:{self.text[:80]}"
        return hashlib.sha256(f"oa:{stable_id}".encode("utf-8")).hexdigest()[:32]


def parse_oa_webhook_event(payload: dict[str, Any]) -> ZaloOAWebhookEvent | None:
    if not isinstance(payload, dict):
        return None

    event_name = str(payload.get("event_name") or payload.get("event") or "").strip()
    message = _as_dict(payload.get("message"))
    sender = _as_dict(payload.get("sender") or payload.get("from"))
    recipient = _as_dict(payload.get("recipient") or payload.get("to"))

    text = _first_text(message.get("text"), payload.get("text"))
    sender_id = _first_text(sender.get("id"), sender.get("user_id"), payload.get("user_id"))
    recipient_id = _first_text(
        recipient.get("id"),
        recipient.get("user_id"),
        payload.get("recipient_id"),
        payload.get("oa_id"),
    )
    message_id = _first_text(
        message.get("msg_id"),
        message.get("message_id"),
        message.get("id"),
        payload.get("msg_id"),
        payload.get("message_id"),
    )
    timestamp = _first_text(
        payload.get("timestamp"),
        payload.get("timeStamp"),
        payload.get("time_stamp"),
        message.get("time"),
    )

    return ZaloOAWebhookEvent(
        event_name=event_name,
        kind=_classify_event(event_name),
        sender_id=sender_id,
        recipient_id=recipient_id,
        message_id=message_id,
        text=text,
        timestamp=timestamp,
        raw=payload,
    )


def _classify_event(event_name: str) -> OAEventKind:
    if event_name in TEXT_MESSAGE_EVENTS:
        return "incoming_text"
    if event_name in MEDIA_MESSAGE_EVENTS:
        return "incoming_media"
    if event_name in CLICK_TO_MESSAGE_EVENTS:
        return "click_to_message"
    if event_name in REACTION_EVENTS:
        return "reaction"
    if event_name in USER_RECEIVED_EVENTS:
        return "user_received"
    if event_name in USER_SEEN_EVENTS:
        return "user_seen"
    if event_name.startswith("oa_send_") and "anonymous" in event_name:
        return "oa_sent_anonymous"
    if event_name.startswith("oa_send_"):
        return "oa_sent"
    return "unknown"


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _first_text(*values: Any) -> str:
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return ""
