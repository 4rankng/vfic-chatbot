"""Recruiter replies must include the inbound Zalo OA message id."""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest


@pytest.mark.asyncio
async def test_recruiter_oa_reply_quotes_latest_inbound_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services.conversation import ConversationService
    from app.services.outbox_service import DispatchResult

    conversation = SimpleNamespace(
        id=uuid.uuid4(),
        zalo_chat_id="oa:user-1",
        zalo_channel="oa",
    )
    recruiter = SimpleNamespace(id=uuid.uuid4())
    inbound = SimpleNamespace(zalo_message_id="inbound-1")
    sent = SimpleNamespace()
    service = ConversationService(AsyncMock())
    service.repo.latest_worker_message = AsyncMock(return_value=inbound)
    service.state.prepare_recruiter_message = AsyncMock(return_value=(sent, 44))
    service.state.finalize_recruiter_delivery = AsyncMock(return_value=sent)
    dispatch = AsyncMock(
        return_value=DispatchResult(
            outbox_id=44,
            message_id=55,
            ok=True,
            zalo_message_id="outbound-1",
        )
    )
    monkeypatch.setattr("app.services.outbox_service.dispatch_outbox", dispatch)

    message, delivered = await service.deliver_recruiter_message(
        conversation, recruiter, "Xin chào"
    )

    assert (message, delivered) == (sent, True)
    prepared = service.state.prepare_recruiter_message.await_args
    assert prepared.kwargs["channel"] == "zalo_oa"
    assert prepared.kwargs["payload"] == {
        "chat_id": "oa:user-1",
        "text": "Xin chào",
        "quote_message_id": "inbound-1",
    }
    dispatch.assert_awaited_once_with(service.db, outbox_id=44)
    service.state.finalize_recruiter_delivery.assert_awaited_once_with(
        conversation,
        message_id=55,
        outbox_id=44,
        delivered=True,
        zalo_message_id="outbound-1",
        external_error=None,
        error_class=None,
    )


@pytest.mark.asyncio
async def test_recruiter_oa_reply_without_inbound_anchor_does_not_create_message() -> None:
    from app.services.conversation import ConversationService
    from app.shared.domain.errors import DeliveryEligibilityError

    conversation = SimpleNamespace(
        id=uuid.uuid4(),
        zalo_chat_id="oa:user-1",
        zalo_channel="oa",
    )
    service = ConversationService(AsyncMock())
    service.repo.latest_worker_message = AsyncMock(return_value=None)
    service.state.prepare_recruiter_message = AsyncMock()

    with pytest.raises(DeliveryEligibilityError):
        await service.deliver_recruiter_message(
            conversation, SimpleNamespace(id=uuid.uuid4()), "Xin chào"
        )

    service.state.prepare_recruiter_message.assert_not_awaited()
