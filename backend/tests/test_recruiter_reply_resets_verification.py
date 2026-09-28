"""Only a human message re-arms the identity-verification attempt cap.

A recruiter reply (``record_recruiter_message`` / ``prepare_recruiter_message``)
clears the per-conversation counter, so a consultant who told the employee the
correct data gives the bot a fresh three tries — and nothing else does.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.conversation import ConversationMode, DeliveryStatus, Message, MessageSender
from app.services.conversation.recruiter_receipts import RecruiterReceiptsMixin


def _mixin() -> RecruiterReceiptsMixin:
    mixin = RecruiterReceiptsMixin()
    mixin.db = AsyncMock()
    mixin.db.add = MagicMock()  # Session.add is sync
    mixin.events = AsyncMock()
    return mixin


def _store_patch() -> tuple[MagicMock, AsyncMock]:
    store = MagicMock()
    store.return_value.reset = AsyncMock()
    return store, store.return_value.reset


@pytest.mark.asyncio
async def test_record_recruiter_message_resets_the_attempts() -> None:
    mixin = _mixin()
    store, reset = _store_patch()
    conv = SimpleNamespace(
        id="11111111-2222-4333-8444-555566667777",
        mode=ConversationMode.HUMAN,
        needs_human=True,
        last_outbound_at=None,
        taken_over_at=None,
        version=3,
        conversation_seq=5,
    )
    recruiter = SimpleNamespace(id="99999999-8888-4777-8666-555566664444")
    result = SimpleNamespace(ok=True, msg_id="m1", error=None)

    with (
        patch(
            "app.services.conversation.recruiter_receipts.TingtingVerifyAttemptsStore",
            store,
        ),
        patch(
            "app.services.conversation.recruiter_receipts.record_audit", new=AsyncMock()
        ),
    ):
        await mixin.record_recruiter_message(conv, recruiter, "đã kiểm tra", result)

    reset.assert_awaited_once_with(conv.id)
    # Operator rule 2026-09-28: the consultant's reply demotes HUMAN to
    # SEMI_AUTO — the bot resumes after the inactivity window without a
    # manual release.
    assert conv.mode == ConversationMode.SEMI_AUTO
    assert conv.needs_human is False


@pytest.mark.asyncio
async def test_prepare_recruiter_message_resets_the_attempts() -> None:
    mixin = _mixin()
    store, reset = _store_patch()
    conv = SimpleNamespace(
        id="22222222-3333-4744-8555-666677778888",
        mode=ConversationMode.HUMAN,
        needs_human=True,
        taken_over_at=None,
        version=1,
        conversation_seq=1,
    )
    recruiter = SimpleNamespace(id="99999999-8888-4777-8666-555566664444")

    with (
        patch(
            "app.services.conversation.recruiter_receipts.TingtingVerifyAttemptsStore",
            store,
        ),
        patch(
            "app.services.conversation.recruiter_receipts.record_audit", new=AsyncMock()
        ),
        patch(
            "app.services.outbox_service.create_pending_outbox",
            new=AsyncMock(return_value=SimpleNamespace(id=44)),
        ),
    ):
        await mixin.prepare_recruiter_message(
            conv,
            recruiter,
            body="gọi lại sau",
            channel="zalo_oa",
            payload={"chat_id": "oa:user-1", "text": "gọi lại sau"},
        )

    reset.assert_awaited_once_with(conv.id)
    # The reset rides a durable human reply: the message row was written SENT/PENDING.
    written: Message = mixin.db.add.call_args.args[0]
    assert written.sender == MessageSender.RECRUITER
    assert written.delivery_status == DeliveryStatus.PENDING
