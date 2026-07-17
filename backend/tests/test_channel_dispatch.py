"""Tests for the Phase 3 channel dispatch service and Zalo adapter wrappers.

Proves:
- Zalo Bot/OA adapters conform to their Protocols and map SendResult →
  ChannelSendResult (including the error_class contract).
- ChannelDispatchService routes by provider through the registry.
- Authority fence: stale generation → suppressed; no active account → suppressed.
- Missing adapter → suppressed provider_error (not a transport failure).
"""

from __future__ import annotations

from unittest.mock import AsyncMock

from app.channels import types as ct
from app.channels.accounts import InMemoryAccountResolver
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
