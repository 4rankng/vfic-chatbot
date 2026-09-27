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
    "follow",
    "unfollow",
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
FOLLOW_EVENTS = {"follow", "user_follow_oa", "user_follow"}
UNFOLLOW_EVENTS = {"unfollow", "user_unfollow_oa", "user_unfollow"}


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
    # All message ids referenced by the event. Zalo sends a single ``msg_id``
    # for most events but an array ``msg_ids`` for ``user_seen_message`` (a user
    # can see several messages at once). Kept as a list so the receipt handler
    # can advance delivery_status for every message in one batch; ``message_id``
    # above remains the first id for backward compatibility.
    message_ids: tuple[str, ...] = ()

    @property
    def scoped_chat_id(self) -> str:
        # Receipt events (user_received_message / user_seen_message) invert the
        # sender/recipient roles: Zalo puts the OA under ``sender`` and the user
        # under ``recipient``. Every other event identifies the user as the
        # sender (or ``follower`` for follow/unfollow). The conversation is
        # always keyed by the user's id, so receipts must scope to recipient.
        user_id = (
            self.recipient_id if self.kind in ("user_received", "user_seen") else self.sender_id
        )
        return f"oa:{user_id}" if user_id else ""

    @property
    def can_start_bot_turn(self) -> bool:
        return self.kind == "incoming_text" and bool(self.sender_id and self.text)

    @property
    def can_trigger_receipt(self) -> bool:
        return self.kind in ("user_seen", "user_received")

    @property
    def is_lifecycle(self) -> bool:
        return self.kind in ("follow", "unfollow")

    @property
    def dedup_hash(self) -> str:
        stable_id = self.message_id or f"{self.event_name}:{self.sender_id}:{self.text[:80]}"
        return hashlib.sha256(f"oa:{stable_id}".encode("utf-8")).hexdigest()[:32]


def oa_id_from_payload(payload: dict[str, Any]) -> str | None:
    """The receiving OA's own id from a webhook body, or ``None``.

    Zalo puts the OA id at the body root (``oa_id``); some event shapes only
    carry it as the recipient. Multi-OA routing keys on this value, and an
    absent or unknown id falls back to the default account.
    """
    if not isinstance(payload, dict):
        return None
    recipient = _as_dict(payload.get("recipient") or payload.get("to"))
    found = _first_text(
        payload.get("oa_id"),
        payload.get("oaId"),
        recipient.get("id"),
        recipient.get("user_id"),
        payload.get("recipient_id"),
    )
    return found or None


def parse_oa_webhook_event(payload: dict[str, Any]) -> ZaloOAWebhookEvent | None:
    if not isinstance(payload, dict):
        return None

    event_name = str(payload.get("event_name") or payload.get("event") or "").strip()
    message = _as_dict(payload.get("message"))
    # Follow/unfollow events identify the user under ``follower`` (not ``sender``);
    # every other event uses ``sender``. Check both so a genuine lifecycle event
    # resolves its user id regardless of which key Zalo populated.
    sender = _as_dict(payload.get("sender") or payload.get("from") or payload.get("follower"))
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
    # user_seen_message sends an array of ids under ``msg_ids``; every other
    # event sends a single id (captured above as ``message_id``). Normalize both
    # into ``message_ids`` so the receipt handler can advance every matched
    # Message row in one pass. Dedup while preserving order.
    raw_ids: list[str] = []
    msg_ids_value = message.get("msg_ids")
    if isinstance(msg_ids_value, list):
        raw_ids.extend(str(mid) for mid in msg_ids_value if str(mid).strip())
    if message_id:
        raw_ids.append(message_id)
    seen_ids: set[str] = set()
    message_ids_list: list[str] = []
    for mid in raw_ids:
        if mid not in seen_ids:
            seen_ids.add(mid)
            message_ids_list.append(mid)
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
        message_ids=tuple(message_ids_list),
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
    if event_name in FOLLOW_EVENTS:
        return "follow"
    if event_name in UNFOLLOW_EVENTS:
        return "unfollow"
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
