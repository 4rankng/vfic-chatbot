"""Preparation-window Zalo chat status on recruiter sends.

While the app prepares a message to a candidate, the candidate's Zalo chat
must show the native temporary status (``sendChatAction``). Only the Zalo Bot
Platform exposes that operation; Zalo OA and Facebook Messenger must send
nothing — and a status failure or stall must never block the send it
accompanies.
"""

from __future__ import annotations

import asyncio
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest


def _install_status_pulses(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[list[tuple[str, str]], list[str]]:
    """Record native typing pulses through the real adapter seam, in order."""
    pulses: list[tuple[str, str]] = []
    order: list[str] = []

    async def _resolve_zalo(self, account_key=None):
        from app.services.integration_settings import ZaloRuntimeConfig

        return ZaloRuntimeConfig(bot_token="test-token")

    async def _send_typing(self, *, account_key, recipient_id):
        from app.channels import types as ct

        pulses.append((account_key, recipient_id))
        order.append("status")
        return ct.ChannelSendResult(ok=True)

    monkeypatch.setattr(
        "app.services.integration_settings.IntegrationSettingsService.resolve_zalo",
        _resolve_zalo,
    )
    monkeypatch.setattr(
        "app.channels.providers.zalo_bot.ZaloBotChannelAdapter.send_typing",
        _send_typing,
    )
    return pulses, order


def _ok_dispatch(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    from app.services.outbox_service import DispatchResult

    dispatch = AsyncMock(
        return_value=DispatchResult(
            outbox_id=44,
            message_id=55,
            ok=True,
            zalo_message_id="outbound-1",
        )
    )
    monkeypatch.setattr("app.services.outbox_service.dispatch_outbox", dispatch)
    return dispatch


def _bot_conversation() -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(), zalo_chat_id="candidate-chat", zalo_channel=None
    )


@pytest.mark.asyncio
async def test_bot_reply_pulses_status_before_the_message_is_prepared(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services.conversation import ConversationService

    pulses, order = _install_status_pulses(monkeypatch)
    _ok_dispatch(monkeypatch)
    conversation = _bot_conversation()
    recruiter = SimpleNamespace(id=uuid.uuid4())
    sent = SimpleNamespace()
    service = ConversationService(AsyncMock())

    async def _prepare(*args, **kwargs):
        order.append("prepared")
        return sent, 44

    service.state.prepare_recruiter_message = AsyncMock(side_effect=_prepare)
    service.state.finalize_recruiter_delivery = AsyncMock(return_value=sent)

    message, delivered = await service.deliver_recruiter_message(
        conversation, recruiter, "Xin chào"
    )

    assert (message, delivered) == (sent, True)
    assert pulses == [("", "candidate-chat")]
    # The status lands while the message is still being prepared, not after.
    assert order == ["status", "prepared"]


@pytest.mark.asyncio
async def test_recruiter_retry_pulses_status_before_redispatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services.conversation import ConversationService

    pulses, _order = _install_status_pulses(monkeypatch)
    _ok_dispatch(monkeypatch)
    service = ConversationService(AsyncMock())
    service.state.retry_recruiter_message = AsyncMock(return_value=44)
    service.state.finalize_recruiter_delivery = AsyncMock(return_value=SimpleNamespace())

    message, delivered = await service.retry_recruiter_message(
        _bot_conversation(), message_id=7
    )

    assert delivered is True
    assert message is not None
    assert pulses == [("", "candidate-chat")]
    service.state.retry_recruiter_message.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("channel", ["zalo_oa", "facebook_messenger"])
async def test_channels_without_a_typing_operation_send_no_status(
    monkeypatch: pytest.MonkeyPatch, channel: str
) -> None:
    from app.services.conversation import ConversationService

    async def _must_not_resolve(self, account_key=None):
        raise AssertionError("config must not be resolved without a typing operation")

    monkeypatch.setattr(
        "app.services.integration_settings.IntegrationSettingsService.resolve_zalo",
        _must_not_resolve,
    )
    _ok_dispatch(monkeypatch)
    if channel == "zalo_oa":
        conversation = SimpleNamespace(
            id=uuid.uuid4(), zalo_chat_id="oa:user-1", zalo_channel="oa"
        )
    else:
        conversation = SimpleNamespace(
            id=uuid.uuid4(),
            zalo_chat_id=None,
            zalo_channel="facebook_messenger",
            channel_identity=SimpleNamespace(
                provider="facebook_messenger",
                account_key="page-1",
                external_id="psid-1",
            ),
        )
    recruiter = SimpleNamespace(id=uuid.uuid4())
    sent = SimpleNamespace()
    service = ConversationService(AsyncMock())
    service.repo.latest_worker_message = AsyncMock(
        return_value=SimpleNamespace(zalo_message_id="inbound-1")
    )
    service.state.prepare_recruiter_message = AsyncMock(return_value=(sent, 44))
    service.state.finalize_recruiter_delivery = AsyncMock(return_value=sent)

    message, delivered = await service.deliver_recruiter_message(
        conversation, recruiter, "Xin chào"
    )

    assert (message, delivered) == (sent, True)


@pytest.mark.asyncio
async def test_status_failure_never_blocks_the_recruiter_send(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services.conversation import ConversationService
    from app.services.integration_settings import ZaloRuntimeConfig

    async def _resolve_zalo(self, account_key=None):
        return ZaloRuntimeConfig(bot_token="test-token")

    async def _unreachable(self, *, account_key, recipient_id):
        raise RuntimeError("zalo unreachable")

    monkeypatch.setattr(
        "app.services.integration_settings.IntegrationSettingsService.resolve_zalo",
        _resolve_zalo,
    )
    monkeypatch.setattr(
        "app.channels.providers.zalo_bot.ZaloBotChannelAdapter.send_typing",
        _unreachable,
    )
    _ok_dispatch(monkeypatch)
    recruiter = SimpleNamespace(id=uuid.uuid4())
    sent = SimpleNamespace()
    service = ConversationService(AsyncMock())
    service.state.prepare_recruiter_message = AsyncMock(return_value=(sent, 44))
    service.state.finalize_recruiter_delivery = AsyncMock(return_value=sent)

    message, delivered = await service.deliver_recruiter_message(
        _bot_conversation(), recruiter, "Xin chào"
    )

    assert (message, delivered) == (sent, True)


@pytest.mark.asyncio
async def test_slow_status_is_dropped_at_the_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import chat_status
    from app.services.integration_settings import ZaloRuntimeConfig

    async def _resolve_zalo(self, account_key=None):
        return ZaloRuntimeConfig(bot_token="test-token")

    async def _stalled(self, *, account_key, recipient_id):
        await asyncio.sleep(30)
        return None

    monkeypatch.setattr(
        "app.services.integration_settings.IntegrationSettingsService.resolve_zalo",
        _resolve_zalo,
    )
    monkeypatch.setattr(
        "app.channels.providers.zalo_bot.ZaloBotChannelAdapter.send_typing",
        _stalled,
    )
    monkeypatch.setattr(chat_status, "PREPARATION_CHAT_STATUS_TIMEOUT_SECONDS", 0.05)

    await asyncio.wait_for(
        chat_status.fire_preparation_chat_status(
            AsyncMock(), channel="zalo_bot", recipient_id="candidate-chat"
        ),
        timeout=1.0,
    )
