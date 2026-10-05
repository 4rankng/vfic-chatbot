"""Tests for the Phase 3 channel dispatch service and Zalo adapter wrappers.

Proves:
- Zalo Bot/OA adapters conform to their Protocols and map SendResult →
  ChannelSendResult (including the error_class contract).
- ChannelDispatchService routes by provider through the registry.
- Authority fence: stale generation → suppressed; no active account → suppressed.
- Missing adapter → suppressed provider_error (not a transport failure).
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.channels import types as ct
from tests.helpers.channel_accounts import InMemoryAccountResolver
from app.channels.dispatch import ChannelDispatchService, build_zalo_registry_from_config
from app.channels.registry import ChannelAdapterRegistry
from app.services.zalo_bot_service import SendResult


def _command(provider: str = ct.PROVIDER_ZALO_BOT, *, generation: int = 1) -> ct.OutboundTextCommand:
    return ct.OutboundTextCommand(
        provider=provider,
        account_key="default:zalo_bot" if provider == ct.PROVIDER_ZALO_BOT else "default:zalo_oa",
        recipient_id="ext-1",
        text="hi",
        channel_account_generation=generation,
    )


# ─── adapter conformance ────────────────────────────────────────────────────


def test_build_zalo_registry_registers_both_providers():
    cfg = type("Cfg", (), {"bot_token": "t", "oa_access_token": "t"})()
    reg = build_zalo_registry_from_config(cfg)
    assert reg.get(ct.PROVIDER_ZALO_BOT) is not None
    assert reg.get(ct.PROVIDER_ZALO_OA) is not None


async def test_zalo_bot_adapter_maps_successful_send():
    from app.channels.providers.zalo_bot import ZaloBotChannelAdapter

    fake_sender = AsyncMock()
    fake_sender.send_message = AsyncMock(
        return_value=SendResult(ok=True, msg_id="bot-mid-1")
    )
    adapter = ZaloBotChannelAdapter(fake_sender)
    result = await adapter.send_text(_command())
    assert isinstance(result, ct.ChannelSendResult)
    assert result.ok
    assert result.provider_message_id == "bot-mid-1"
    assert not result.is_send_unknown


async def test_zalo_bot_adapter_maps_ambiguous_transport_to_send_unknown():
    from app.channels.providers.zalo_bot import ZaloBotChannelAdapter

    fake_sender = AsyncMock()
    fake_sender.send_message = AsyncMock(
        return_value=SendResult(ok=False, error="timeout", error_class="read_timeout")
    )
    adapter = ZaloBotChannelAdapter(fake_sender)
    result = await adapter.send_text(_command())
    assert not result.ok
    assert result.is_send_unknown  # read_timeout → non-retriable
    assert result.error_class == "read_timeout"


async def test_zalo_adapter_retains_accepted_prefix_id_on_partial_failure():
    from app.channels.providers.zalo_bot import ZaloBotChannelAdapter

    sender = SimpleNamespace(send_message=AsyncMock(return_value=SendResult(
        ok=False, msg_id="accepted-prefix", partial=True,
        error="partial_delivery: tail rejected", error_class="unknown",
    )))
    result = await ZaloBotChannelAdapter(sender).send_text(_command())
    assert result.is_send_unknown
    assert result.provider_message_id == "accepted-prefix"
    assert result.error.startswith("partial_delivery: ")


async def test_zalo_bot_adapter_maps_unclassified_failure_to_provider_error():
    """When the sender omits error_class, the adapter defaults to provider_error
    (retryable FAILED), never SEND_UNKNOWN — and never violates the Phase 1
    contract that error_class is required on failure."""
    from app.channels.providers.zalo_bot import ZaloBotChannelAdapter

    fake_sender = AsyncMock()
    fake_sender.send_message = AsyncMock(
        return_value=SendResult(ok=False, error="bad request", error_class=None)
    )
    adapter = ZaloBotChannelAdapter(fake_sender)
    result = await adapter.send_text(_command())
    assert not result.ok
    assert result.error_class == "provider_error"
    assert not result.is_send_unknown


async def test_zalo_oa_adapter_passes_quote_message_id():
    from app.channels.providers.zalo_oa import ZaloOAChannelAdapter

    fake_sender = AsyncMock()
    fake_sender.send_message = AsyncMock(
        return_value=SendResult(ok=True, msg_id="oa-mid-1")
    )
    adapter = ZaloOAChannelAdapter(fake_sender)
    cmd = ct.OutboundTextCommand(
        provider=ct.PROVIDER_ZALO_OA,
        account_key="default:zalo_oa",
        recipient_id="oa-user",
        text="reply",
        channel_account_generation=1,
        reply_to_message_id="inbound-mid",
    )
    result = await adapter.send_text(cmd)
    assert result.ok
    # OA send_message must receive the quote_message_id kwarg
    assert fake_sender.send_message.await_args.kwargs["quote_message_id"] == "inbound-mid"


def test_zalo_oa_adapter_parse_receipt_maps_seen_to_read():
    from app.channels.providers.zalo_oa import ZaloOAChannelAdapter

    fake_sender = AsyncMock()
    adapter = ZaloOAChannelAdapter(fake_sender)
    receipt = adapter.parse_receipt(
        {
            "event_name": "user_seen_message",
            "message": {"msg_id": "oa-msg-9"},
        }
    )
    assert receipt is not None
    assert receipt.kind == "read"
    assert "oa-msg-9" in receipt.provider_message_ids

    assert adapter.parse_receipt({"event_name": "follow"}) is None
    assert adapter.parse_receipt({"event_name": "user_seen_message", "message": {}}) is None


# ─── dispatch service routing ───────────────────────────────────────────────


class _RecordingAdapter:
    """Captures the command for assertions."""

    def __init__(self, provider: str, *, result: ct.ChannelSendResult | None = None) -> None:
        self.provider = provider
        self._result = result or ct.ChannelSendResult(
            ok=True, provider_message_id=f"{provider}-mid"
        )
        self.sent: list[ct.OutboundTextCommand] = []

    async def send_text(self, command: ct.OutboundTextCommand) -> ct.ChannelSendResult:
        self.sent.append(command)
        return self._result


async def test_dispatch_routes_to_registered_adapter():
    bot = _RecordingAdapter(ct.PROVIDER_ZALO_BOT)
    reg = ChannelAdapterRegistry()
    reg.register(bot)
    svc = ChannelDispatchService(reg)
    result = await svc.send(_command(ct.PROVIDER_ZALO_BOT))
    assert result.ok
    assert bot.sent and bot.sent[0].provider == ct.PROVIDER_ZALO_BOT


async def test_dispatch_missing_adapter_is_suppressed_provider_error():
    """No adapter for a provider is a configuration issue, not a transport
    failure. Suppress rather than retry — retrying would loop forever."""
    reg = ChannelAdapterRegistry()
    svc = ChannelDispatchService(reg)
    result = await svc.send(_command(ct.PROVIDER_ZALO_BOT))
    assert not result.ok
    assert result.suppressed
    assert result.error_class == "provider_error"
    assert not result.is_send_unknown


# ─── authority fence ────────────────────────────────────────────────────────


async def test_dispatch_suppresses_when_account_generation_advanced():
    """A command queued under generation 1 that finds generation 2 active is
    suppressed — the account was reconnected/replaced after it was queued."""
    resolver = InMemoryAccountResolver()
    resolver.upsert(
        ct.ChannelAccountRef(
            id="id-1",
            provider=ct.PROVIDER_ZALO_BOT,
            account_key="default:zalo_bot",
            label="Zalo",
            status="ACTIVE",
            generation=2,  # command has generation=1
        )
    )
    reg = ChannelAdapterRegistry()
    bot = _RecordingAdapter(ct.PROVIDER_ZALO_BOT)
    reg.register(bot)
    svc = ChannelDispatchService(reg, account_resolver=resolver)
    result = await svc.send(_command(ct.PROVIDER_ZALO_BOT, generation=1))
    assert not result.ok
    assert result.suppressed
    assert bot.sent == []  # adapter never called


async def test_dispatch_suppresses_when_account_inactive():
    resolver = InMemoryAccountResolver()
    resolver.upsert(
        ct.ChannelAccountRef(
            id="id-1",
            provider=ct.PROVIDER_ZALO_BOT,
            account_key="default:zalo_bot",
            label="Zalo",
            status="INACTIVE",
            generation=1,
        )
    )
    reg = ChannelAdapterRegistry()
    bot = _RecordingAdapter(ct.PROVIDER_ZALO_BOT)
    reg.register(bot)
    svc = ChannelDispatchService(reg, account_resolver=resolver)
    result = await svc.send(_command(ct.PROVIDER_ZALO_BOT, generation=1))
    assert not result.ok
    assert result.suppressed
    assert bot.sent == []


async def test_dispatch_proceeds_when_generation_matches():
    resolver = InMemoryAccountResolver()
    resolver.upsert(
        ct.ChannelAccountRef(
            id="id-1",
            provider=ct.PROVIDER_ZALO_BOT,
            account_key="default:zalo_bot",
            label="Zalo",
            status="ACTIVE",
            generation=1,  # matches command
        )
    )
    reg = ChannelAdapterRegistry()
    bot = _RecordingAdapter(ct.PROVIDER_ZALO_BOT)
    reg.register(bot)
    svc = ChannelDispatchService(reg, account_resolver=resolver)
    result = await svc.send(_command(ct.PROVIDER_ZALO_BOT, generation=1))
    assert result.ok
    assert len(bot.sent) == 1


async def test_dispatch_rejects_a_command_from_an_unrecognized_future_generation():
    resolver = InMemoryAccountResolver()
    resolver.upsert(ct.ChannelAccountRef(
        id="id-1", provider=ct.PROVIDER_ZALO_BOT, account_key="default:zalo_bot",
        label="Zalo", status="ACTIVE", generation=1,
    ))
    adapter = _RecordingAdapter(ct.PROVIDER_ZALO_BOT)
    registry = ChannelAdapterRegistry()
    registry.register(adapter)

    result = await ChannelDispatchService(registry, account_resolver=resolver).send(
        _command(generation=2),
    )

    assert result.suppressed
    assert adapter.sent == []


async def test_dispatch_without_resolver_skips_fence():
    """When no resolver is wired, the dispatch service routes unconditionally —
    backwards-compatible with the existing outbox path which has no account
    awareness yet."""
    reg = ChannelAdapterRegistry()
    bot = _RecordingAdapter(ct.PROVIDER_ZALO_BOT)
    reg.register(bot)
    svc = ChannelDispatchService(reg, account_resolver=None)
    result = await svc.send(_command(ct.PROVIDER_ZALO_BOT, generation=1))
    assert result.ok
    assert len(bot.sent) == 1


@pytest.mark.parametrize("provider", [ct.PROVIDER_ZALO_BOT, ct.PROVIDER_ZALO_OA, ct.PROVIDER_FACEBOOK_MESSENGER])
async def test_dispatch_delivers_every_project_in_bounded_parts(provider):
    adapter = _RecordingAdapter(provider)
    registry = ChannelAdapterRegistry()
    registry.register(adapter)
    names = ("LG Display", "Rorze", "Amtran", "Kyocera", "Pegatron")
    text = "\n\n".join(
        (f"{index}. {name}: " + "Thông tin công việc đã xác minh. " * 15).rstrip()
        for index, name in enumerate(names, 1)
    )
    command = replace(_command(provider), text=text)

    result = await ChannelDispatchService(registry).send(command)

    assert result.ok
    assert len(adapter.sent) >= 2
    assert all(len(part.text) <= 1600 for part in adapter.sent)
    assert "\n\n".join(part.text for part in adapter.sent) == text
    assert all(part.account_key == command.account_key for part in adapter.sent)
    assert all(part.recipient_id == command.recipient_id for part in adapter.sent)
    assert result.telemetry.chunk_count == len(adapter.sent)


async def test_later_part_policy_expiry_preserves_accepted_prefix_as_send_unknown():
    adapter = _RecordingAdapter(ct.PROVIDER_FACEBOOK_MESSENGER)
    registry = ChannelAdapterRegistry()
    registry.register(adapter)
    command = replace(_command(ct.PROVIDER_FACEBOOK_MESSENGER), text="Dự án đã xác minh. " * 200)
    guards = 0

    def guard():
        nonlocal guards
        guards += 1
        return None if guards == 1 else ct.ChannelSendResult(
            ok=False, suppressed=True, error="window expired", error_class="policy_suppressed",
        )

    result = await ChannelDispatchService(registry).send(command, before_provider_io=guard)

    assert len(adapter.sent) == 1
    assert guards == 2
    assert not result.ok
    assert not result.suppressed
    assert result.is_send_unknown
    assert result.provider_message_id == "facebook_messenger-mid"


async def test_later_part_account_replacement_stops_the_remaining_parts():
    provider = ct.PROVIDER_FACEBOOK_MESSENGER
    adapter = _RecordingAdapter(provider)
    registry = ChannelAdapterRegistry()
    registry.register(adapter)
    command = replace(_command(provider), text="Dự án đã xác minh. " * 200)
    account = ct.ChannelAccountRef(
        id="page-1", provider=provider, account_key=command.account_key,
        label="Page", status="ACTIVE", generation=1,
    )
    resolver = SimpleNamespace(resolve_active=AsyncMock(side_effect=[account, replace(account, generation=2)]))

    result = await ChannelDispatchService(registry, account_resolver=resolver).send(command)

    assert len(adapter.sent) == 1
    assert resolver.resolve_active.await_count == 2
    assert result.is_send_unknown
    assert not result.suppressed


async def test_failed_second_part_cannot_be_retried_as_a_whole_answer():
    provider = ct.PROVIDER_FACEBOOK_MESSENGER
    adapter = _RecordingAdapter(provider)
    adapter.send_text = AsyncMock(side_effect=[
        ct.ChannelSendResult(ok=True, provider_message_id="accepted-1"),
        ct.ChannelSendResult(ok=False, error="rejected", error_class="provider_error"),
    ])
    registry = ChannelAdapterRegistry()
    registry.register(adapter)
    command = replace(_command(provider), text="Dự án đã xác minh. " * 200)

    result = await ChannelDispatchService(registry).send(command)

    assert adapter.send_text.await_count == 2
    assert not result.ok
    assert result.is_send_unknown
    assert result.provider_message_id == "accepted-1"


async def test_later_part_exception_retains_accepted_id_without_exposing_error_text():
    provider = ct.PROVIDER_FACEBOOK_MESSENGER
    adapter = _RecordingAdapter(provider)
    adapter.send_text = AsyncMock(side_effect=[
        ct.ChannelSendResult(ok=True, provider_message_id="accepted-1"),
        RuntimeError("private provider envelope"),
    ])
    registry = ChannelAdapterRegistry()
    registry.register(adapter)
    command = replace(_command(provider), text="Dự án đã xác minh. " * 200)

    result = await ChannelDispatchService(registry).send(command)

    assert result.is_send_unknown
    assert result.provider_message_id == "accepted-1"
    assert "private" not in result.error
    assert adapter.send_text.await_count == 2
    assert result.telemetry.provider_attempts == 2
    assert result.telemetry.chunk_count == 2


async def test_first_part_rejection_stays_a_definite_failure():
    provider = ct.PROVIDER_FACEBOOK_MESSENGER
    adapter = _RecordingAdapter(provider, result=ct.ChannelSendResult(
        ok=False, error="provider rejected", error_class="provider_error",
    ))
    registry = ChannelAdapterRegistry()
    registry.register(adapter)

    result = await ChannelDispatchService(registry).send(replace(
        _command(provider), text="Dự án đã xác minh. " * 200,
    ))

    assert not result.is_send_unknown
    assert result.error_class == "provider_error"
    assert len(adapter.sent) == 1


async def test_real_messenger_adapter_receives_every_bounded_project_part(monkeypatch):
    from app.channels.providers.facebook_messenger import FacebookMessengerAdapter

    provider = ct.PROVIDER_FACEBOOK_MESSENGER
    cfg = SimpleNamespace(page_id="PAGE-1")
    adapter = FacebookMessengerAdapter(cfg)
    registry = ChannelAdapterRegistry()
    registry.register(adapter)
    names = ("LG Display", "Rorze", "Amtran", "Kyocera", "Pegatron")
    text = "\n\n".join(
        (f"{index}. {name}: " + "Thông tin công việc đã xác minh. " * 15).rstrip()
        for index, name in enumerate(names, 1)
    )
    sender = AsyncMock(return_value={"message_id": "accepted-first"})
    monkeypatch.setattr("app.channels.providers.facebook_messenger.graph_send_message", sender)
    command = replace(_command(provider), account_key="PAGE-1", text=text)

    result = await ChannelDispatchService(registry).send(command)

    assert result.ok
    bodies = [call.kwargs["text"] for call in sender.await_args_list]
    assert len(bodies) >= 2
    assert all(len(body) <= 1600 for body in bodies)
    assert "\n\n".join(bodies) == text
    assert result.provider_message_id == "accepted-first"
    assert all(call.kwargs["recipient_psid"] == command.recipient_id for call in sender.await_args_list)


# ─── OA prefix regression (Critical finding from Phase 3 review) ────────────


async def test_zalo_oa_adapter_strips_storage_prefix_from_recipient():
    """OA conversations store the scoped chat id as 'oa:<user_id>'; the OA Send
    API needs the raw user id. Regression guard: the legacy ZaloChannelSender
    stripped this prefix; the neutral adapter must too, or every OA outbound
    sends recipient.user_id='oa:...' and Zalo rejects it.
    """
    from app.channels.providers.zalo_oa import ZaloOAChannelAdapter

    fake_sender = AsyncMock()
    fake_sender.send_message = AsyncMock(return_value=SendResult(ok=True, msg_id="oa-1"))
    adapter = ZaloOAChannelAdapter(fake_sender)
    cmd = ct.OutboundTextCommand(
        provider=ct.PROVIDER_ZALO_OA,
        account_key="default:zalo_oa",
        recipient_id="oa:user-42",  # the prefixed scoped chat id
        text="reply",
        channel_account_generation=1,
    )
    await adapter.send_text(cmd)
    # The OA sender must receive the STRIPPED user id, not 'oa:user-42'.
    sent_chat_id = fake_sender.send_message.await_args.args[0]
    assert sent_chat_id == "user-42"
    assert not sent_chat_id.startswith("oa:")


async def test_try_neutral_dispatch_routes_oa_with_stripped_recipient():
    """End-to-end regression: an outbox row with an OA-prefixed chat_id payload
    dispatches through the neutral path and the underlying sender sees the
    stripped user id. This is the exact path the Phase 3 review flagged.
    """
    from app.services.outbox_service import _try_neutral_dispatch, DispatchCandidate

    received_chat_ids: list[str] = []

    class _StubOA:
        async def send_message(self, chat_id, text, *, quote_message_id=""):
            received_chat_ids.append(chat_id)
            from app.services.zalo_bot_service import SendResult

            return SendResult(ok=True, msg_id="oa-mid")

    # Patch build_zalo_registry_from_config to register a real OA adapter
    # wrapping our stub sender.
    from app.channels.providers.zalo_oa import ZaloOAChannelAdapter
    import app.channels.dispatch as dispatch_mod

    original_build = dispatch_mod.build_zalo_registry_from_config

    def _fake_build(cfg, *, oa_refresh=None, oa_account_key=""):
        from app.channels.registry import ChannelAdapterRegistry

        reg = ChannelAdapterRegistry()
        # Bypass from_config; inject our stub-backed adapter directly.
        reg.register(ZaloOAChannelAdapter(_StubOA()))
        return reg

    dispatch_mod.build_zalo_registry_from_config = _fake_build  # type: ignore[assignment]
    try:
        candidate = DispatchCandidate(
            outbox_id=1,
            message_id=10,
            channel="zalo_oa",
            payload={"chat_id": "oa:user-99", "text": "hi"},
        )
        outbox = type(
            "Outbox",
            (),
            {"channel_account_generation": None},
        )()
        cfg = type("Cfg", (), {"bot_token": "t", "oa_access_token": "t"})()
        result = await _try_neutral_dispatch(
            None,
            candidate,
            outbox,
            cfg,
            integration_settings=None,
            oa_refresh=None,
        )
    finally:
        dispatch_mod.build_zalo_registry_from_config = original_build  # type: ignore[assignment]

    assert result is not None
    assert result.ok
    assert received_chat_ids == ["user-99"]  # stripped, not 'oa:user-99'
    assert result.provider_message_id == "oa-mid"


async def test_try_neutral_dispatch_declines_media_payloads():
    """Media outbox payloads fall back to the legacy ZaloChannelSender path.

    The neutral registry builds text commands only; a media payload routed
    through it would keep the caption but silently lose the attachment, so the
    neutral path declines it and the legacy OA media send owns the dispatch.
    """
    from app.services.outbox_service import DispatchCandidate, _try_neutral_dispatch

    candidate = DispatchCandidate(
        outbox_id=1,
        message_id=10,
        channel="zalo_oa",
        payload={
            "chat_id": "oa:tingting:user-9",
            "text": "caption",
            "media_url": "https://bot.tingting.vip/tingting/tu-cham-cong.png",
            "media_type": "image",
            "quote_message_id": "inb-1",
        },
    )
    result = await _try_neutral_dispatch(None, candidate, None, None, None, None)
    assert result is None


async def test_facade_send_payload_media_routes_to_oa_send_media():
    """A media outbox payload upgrades the OA send to the CS media template.

    The caption and quote ride along; only the media fields turn the text send
    into a media send, addressed to the stripped user id.
    """
    from types import SimpleNamespace

    from app.services.zalo_bot_service import SendResult
    from app.services.zalo_sender import ZaloChannelSender

    class _StubOA:
        def __init__(self) -> None:
            self.media_calls: list[tuple] = []

        async def send_media(
            self, chat_id, *, text, media_url, media_type="image", quote_message_id=""
        ):
            self.media_calls.append((chat_id, text, media_url, media_type, quote_message_id))
            return SendResult(ok=True, msg_id="oa-media-1")

        async def send_message(self, *args, **kwargs):
            raise AssertionError("media payload must not take the text send path")

    oa = _StubOA()
    facade = SimpleNamespace(_oa=oa)
    result = await ZaloChannelSender.send_payload(
        facade,
        "zalo_oa",
        {
            "chat_id": "oa:tingting:user-9",
            "text": "Dạ anh/chị mở ứng dụng TingTing…",
            "media_url": "https://bot.tingting.vip/tingting/tu-cham-cong.png",
            "media_type": "image",
            "quote_message_id": "inb-1",
        },
    )
    assert result.ok
    assert oa.media_calls == [
        (
            "user-9",
            "Dạ anh/chị mở ứng dụng TingTing…",
            "https://bot.tingting.vip/tingting/tu-cham-cong.png",
            "image",
            "inb-1",
        )
    ]


def test_provider_for_outbox_channel_includes_facebook_messenger():
    """Phase 6: the Messenger adapter is now registered for outbound dispatch,
    so facebook_messenger maps to its provider id (not None). Unknown channels
    still fall back to the legacy path."""
    from app.services.outbox_service import _provider_for_outbox_channel

    assert _provider_for_outbox_channel("zalo_bot") == "zalo_bot"
    assert _provider_for_outbox_channel("zalo_oa") == "zalo_oa"
    assert _provider_for_outbox_channel("facebook_messenger") == "facebook_messenger"
    assert _provider_for_outbox_channel("unknown") is None


@pytest.mark.parametrize(
    ("last_inbound_at", "expected_error"),
    [
        (
            datetime.now(timezone.utc) - timedelta(hours=24, seconds=1),
            "messenger standard messaging window expired",
        ),
        (None, "messenger standard messaging window is not open"),
    ],
)
async def test_facebook_dispatch_suppresses_closed_messaging_window(
    monkeypatch,
    last_inbound_at,
    expected_error,
):
    """The real Messenger outbox path must enforce policy before provider I/O."""
    from app.services.outbox_service import DispatchCandidate, _dispatch_facebook

    class _FakeDB:
        async def get(self, model, object_id):
            return SimpleNamespace(conversation_id="conversation-1")

        async def execute(self, stmt):
            return SimpleNamespace(
                first=lambda: SimpleNamespace(
                    account_key="page-1",
                    external_id="psid-1",
                    last_inbound_at=last_inbound_at,
                )
            )

    class _IntegrationSettings:
        async def resolve_facebook(self, page_id):
            return SimpleNamespace(page_id=page_id)

    def _unexpected_registry_build(config):
        raise AssertionError("expired Messenger send reached the provider adapter")

    monkeypatch.setattr(
        "app.channels.dispatch.build_facebook_registry",
        _unexpected_registry_build,
    )

    result = await _dispatch_facebook(
        _FakeDB(),
        DispatchCandidate(
            outbox_id=1,
            message_id=10,
            channel="facebook_messenger",
            payload={"text": "Xin chào"},
        ),
        SimpleNamespace(channel_account_generation=1),
        _IntegrationSettings(),
    )

    assert result is not None
    assert not result.ok
    assert result.suppressed
    assert result.error == expected_error
    assert result.error_class == "policy_suppressed"


async def test_facebook_dispatch_allows_open_messaging_window(monkeypatch):
    """A current inbound window reaches the adapter with the stored Page fence."""
    from app.services.outbox_service import DispatchCandidate, _dispatch_facebook

    last_inbound_at = datetime.now(timezone.utc) - timedelta(hours=1)

    class _FakeDB:
        async def get(self, model, object_id):
            return SimpleNamespace(conversation_id="conversation-1")

        async def execute(self, stmt):
            return SimpleNamespace(
                first=lambda: SimpleNamespace(
                    account_key="page-1",
                    external_id="psid-1",
                    last_inbound_at=last_inbound_at,
                )
            )

    class _IntegrationSettings:
        async def resolve_facebook(self, page_id):
            return SimpleNamespace(page_id=page_id)

    resolver = InMemoryAccountResolver()
    resolver.upsert(
        ct.ChannelAccountRef(
            id="account-1",
            provider=ct.PROVIDER_FACEBOOK_MESSENGER,
            account_key="page-1",
            label="Page 1",
            status="ACTIVE",
            generation=7,
        )
    )
    adapter = _RecordingAdapter(ct.PROVIDER_FACEBOOK_MESSENGER)
    registry = ChannelAdapterRegistry()
    registry.register(adapter)

    monkeypatch.setattr(
        "app.channels.dispatch.build_facebook_registry",
        lambda config: registry,
    )
    monkeypatch.setattr(
        "app.channels.providers.facebook_account.FacebookAccountResolver",
        lambda db: resolver,
    )

    result = await _dispatch_facebook(
        _FakeDB(),
        DispatchCandidate(
            outbox_id=1,
            message_id=10,
            channel="facebook_messenger",
            payload={"text": "Xin chào"},
        ),
        SimpleNamespace(channel_account_generation=7),
        _IntegrationSettings(),
    )

    assert result is not None
    assert result.ok
    assert len(adapter.sent) == 1
    assert adapter.sent[0].channel_account_generation == 7


async def test_facebook_dispatch_revalidates_window_immediately_before_send(monkeypatch):
    """A window that closes during setup is suppressed before adapter I/O."""
    from app.channels.providers.facebook_policy import PolicyDecision
    from app.services.outbox_service import DispatchCandidate, _dispatch_facebook

    class _FakeDB:
        async def get(self, model, object_id):
            return SimpleNamespace(conversation_id="conversation-1")

        async def execute(self, stmt):
            return SimpleNamespace(
                first=lambda: SimpleNamespace(
                    account_key="page-1",
                    external_id="psid-1",
                    last_inbound_at=datetime.now(timezone.utc) - timedelta(hours=1),
                )
            )

    class _IntegrationSettings:
        async def resolve_facebook(self, page_id):
            return SimpleNamespace(page_id=page_id)

    resolver = InMemoryAccountResolver()
    resolver.upsert(
        ct.ChannelAccountRef(
            id="account-1",
            provider=ct.PROVIDER_FACEBOOK_MESSENGER,
            account_key="page-1",
            label="Page 1",
            status="ACTIVE",
            generation=7,
        )
    )
    adapter = _RecordingAdapter(ct.PROVIDER_FACEBOOK_MESSENGER)
    registry = ChannelAdapterRegistry()
    registry.register(adapter)
    decisions = iter(
        [
            PolicyDecision(allowed=True, window_remaining_seconds=0.01),
            PolicyDecision(allowed=False, reason="window_expired"),
        ]
    )

    monkeypatch.setattr(
        "app.channels.providers.facebook_policy.evaluate_send_eligibility",
        lambda **kwargs: next(decisions),
    )
    monkeypatch.setattr(
        "app.channels.dispatch.build_facebook_registry",
        lambda config: registry,
    )
    monkeypatch.setattr(
        "app.channels.providers.facebook_account.FacebookAccountResolver",
        lambda db: resolver,
    )

    result = await _dispatch_facebook(
        _FakeDB(),
        DispatchCandidate(
            outbox_id=1,
            message_id=10,
            channel="facebook_messenger",
            payload={"text": "Xin chào"},
        ),
        SimpleNamespace(channel_account_generation=7),
        _IntegrationSettings(),
    )

    assert result is not None
    assert result.suppressed
    assert result.error_class == "policy_suppressed"
    assert adapter.sent == []
