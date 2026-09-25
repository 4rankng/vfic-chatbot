"""Permanent recipient-unreachable handling for outbound sends.

Zalo OA ``-201 user_id is not valid`` is a property of the recipient, not of
the request: the id is not a sendable user of the OA the access token belongs
to (the user unfollowed, or the inbound events originate from a different OA
sharing the webhook URL). Retrying the same send can never succeed, so the
finalizers record that once per conversation — a CRM-visible system note and a
follow-up opt-out — instead of leaving the recruiter to loop on "Thử lại".
"""

from __future__ import annotations

from sqlalchemy import func, select

from app.conversation_messaging.domain.statuses import MessageSender
from app.models.conversation import Conversation, Message

# The ``user_unreachable`` OutboundErrorClass produced by the Zalo OA sender.
USER_UNREACHABLE_SEND_CLASS = "user_unreachable"

# Stable marker inside the system note body — the dedupe key so one
# conversation never accumulates a note per failed send.
_NOTE_MARKER = "user_id is invalid"

_NOTE_BODY = (
    "Zalo từ chối người nhận: user_id is invalid — không thể gửi tin cho người "
    "dùng này qua OA hiện tại (người dùng có thể đã bỏ quan tâm OA, hoặc sự "
    "kiện đến từ một OA khác với OA đang cấu hình). Thử lại sẽ không thành công."
)


async def apply_user_unreachable_side_effects(db, conv: Conversation, events) -> None:
    """Stamp the conversation once: follow-up opt-out + an explanatory note.

    Best-effort by design: a failure here must never break the send
    finalization that already committed. The note does not bump unread_count
    or last_inbound_at (SYSTEM chrome, mirroring record_system_note).
    """
    try:
        if str(getattr(conv, "zalo_channel", "") or "") != "oa":
            return
        conv.followup_opted_out = True
        existing = await db.scalar(
            select(func.count())
            .select_from(Message)
            .where(
                Message.conversation_id == conv.id,
                Message.sender == MessageSender.SYSTEM,
                Message.body.contains(_NOTE_MARKER),
            )
        )
        if not existing:
            db.add(Message(conversation_id=conv.id, sender=MessageSender.SYSTEM, body=_NOTE_BODY))
        await db.commit()
        await events.conversation_updated(conv)
    except Exception:  # noqa: BLE001 — CRM chrome must never break finalization
        import logging

        logging.getLogger(__name__).debug(
            "user-unreachable side effects failed conversation=%s",
            getattr(conv, "id", "?"),
            exc_info=True,
        )
