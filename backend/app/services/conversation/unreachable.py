"""Permanent recipient-unreachable handling for outbound sends.

Some provider refusals are a property of the recipient, not of the request:

- Zalo OA ``-201 user_id is not valid`` — the id is not a sendable user of
  the OA the access token belongs to (the user unfollowed, or the inbound
  events originate from a different OA sharing the webhook URL).
- Messenger code 551 "This person isn't available right now" — the recipient
  blocked the Page or messaging, or the account is deactivated/restricted.

Retrying either can never succeed, so the finalizers record that once per
conversation — a CRM-visible system note and a follow-up opt-out — instead of
leaving the recruiter to loop on "Thử lại".
"""

from __future__ import annotations

from sqlalchemy import func, select

from app.conversation_messaging.domain.statuses import MessageSender
from app.models.conversation import Conversation, Message

# The ``user_unreachable`` OutboundErrorClass produced by the Zalo OA sender
# and the Messenger adapter.
USER_UNREACHABLE_SEND_CLASS = "user_unreachable"

# Stable marker inside the system note body — the dedupe key so one
# conversation never accumulates a note per failed send.
_NOTE_MARKER = "user_id is invalid"

_NOTE_BODY = (
    "Zalo từ chối người nhận: user_id is invalid — không thể gửi tin cho người "
    "dùng này qua OA hiện tại (người dùng có thể đã bỏ quan tâm OA, hoặc sự "
    "kiện đến từ một OA khác với OA đang cấu hình). Thử lại sẽ không thành công."
)

_MESSENGER_NOTE_MARKER = "Messenger từ chối người nhận"

_MESSENGER_NOTE_BODY = (
    "Messenger từ chối người nhận: code=551 (This person isn't available right "
    "now) — người dùng không thể nhận tin nhắn qua Messenger (có thể đã chặn "
    "trang hoặc vô hiệu hóa tài khoản). Thử lại sẽ không thành công."
)

# Per-channel (marker, body) for the once-per-conversation note. Channels not
# listed here have no ``user_unreachable`` producer yet and are left untouched.
_CHANNEL_NOTES: dict[str, tuple[str, str]] = {
    "oa": (_NOTE_MARKER, _NOTE_BODY),
    "facebook_messenger": (_MESSENGER_NOTE_MARKER, _MESSENGER_NOTE_BODY),
}


async def apply_user_unreachable_side_effects(db, conv: Conversation, events) -> None:
    """Stamp the conversation once: follow-up opt-out + an explanatory note.

    Best-effort by design: a failure here must never break the send
    finalization that already committed. The note does not bump unread_count
    or last_inbound_at (SYSTEM chrome, mirroring record_system_note).
    """
    try:
        note = _CHANNEL_NOTES.get(str(getattr(conv, "zalo_channel", "") or ""))
        if note is None:
            return
        marker, body = note
        conv.followup_opted_out = True
        existing = await db.scalar(
            select(func.count())
            .select_from(Message)
            .where(
                Message.conversation_id == conv.id,
                Message.sender == MessageSender.SYSTEM,
                Message.body.contains(marker),
            )
        )
        if not existing:
            db.add(Message(conversation_id=conv.id, sender=MessageSender.SYSTEM, body=body))
        await db.commit()
        await events.conversation_updated(conv)
    except Exception:  # noqa: BLE001 — CRM chrome must never break finalization
        import logging

        logging.getLogger(__name__).debug(
            "user-unreachable side effects failed conversation=%s",
            getattr(conv, "id", "?"),
            exc_info=True,
        )
