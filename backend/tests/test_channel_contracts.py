"""Contract, capability, and conformance tests for the neutral channel layer.

Phase 1 coverage:

- Immutable value objects validate inputs and redact identifiers in ``repr``.
- :class:`ChannelAdapterRegistry` fails closed for unknown/missing providers.
- Optional capabilities (typing, receipt) are returned as ``None`` when
  absent — no ``hasattr`` checks in business logic.
- ``ChannelSendResult.is_send_unknown`` reuses the shared ambiguous-transport
  taxonomy so the delivery state machine does not branch on provider.
- A test-only third provider passes the same text-adapter conformance suite
  Zalo/Messenger will use. This is the "future provider fits without changing
  shared contracts" guarantee (Red Team finding #15, retained by user demand).
- Diagnostic data never carries text, tokens, or full external ids.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

import pytest

from app.channels.accounts import ChannelAccountStatus
from tests.helpers.channel_accounts import InMemoryAccountResolver
from app.channels.ports import (
    ChannelAccountResolver,
    ReceiptCapability,
    TextChannelAdapter,
    TypingCapability,
)
from app.channels.registry import ChannelAdapterRegistry
from app.channels.types import (
    PROVIDER_FACEBOOK_MESSENGER,
    PROVIDER_ZALO_BOT,
    PROVIDER_ZALO_OA,
    ChannelAccountRef,
    ChannelIdentityRef,
    ChannelInboundMessage,
    ChannelReceipt,
    ChannelSendResult,
    OutboundTextCommand,
    is_known_provider,
)


# ─── fixtures ────────────────────────────────────────────────────────────────


def _identity(
    provider: str = PROVIDER_ZALO_BOT,
    account_key: str = "default:zalo_bot",
    external_id: str = "ext-123",
) -> ChannelIdentityRef:
    return ChannelIdentityRef(
        provider=provider, account_key=account_key, external_id=external_id
    )


def _account_ref(
    *,
    provider: str = PROVIDER_FACEBOOK_MESSENGER,
    account_key: str = "page-111",
    status: str = ChannelAccountStatus.ACTIVE,
    generation: int = 1,
) -> ChannelAccountRef:
    return ChannelAccountRef(
        id="00000000-0000-4000-8000-000000000001",
        provider=provider,
        account_key=account_key,
        label="My Page",
        status=status,
        generation=generation,
    )


# ─── provider id validation ──────────────────────────────────────────────────


def test_installed_provider_ids_are_known():
    assert is_known_provider(PROVIDER_ZALO_BOT)
    assert is_known_provider(PROVIDER_ZALO_OA)
    assert is_known_provider(PROVIDER_FACEBOOK_MESSENGER)


def test_future_provider_ids_are_not_known():
    """Telegram/WhatsApp are conformance targets only; they must not be
    selectable until their adapter exists."""
    assert not is_known_provider("telegram")
    assert not is_known_provider("whatsapp")
    assert not is_known_provider("")


# ─── identity / account refs ─────────────────────────────────────────────────


def test_identity_ref_requires_all_three_components():
    with pytest.raises(ValueError):
        ChannelIdentityRef(provider="", account_key="k", external_id="x")
    with pytest.raises(ValueError):
        ChannelIdentityRef(provider="zalo_bot", account_key="", external_id="x")
    with pytest.raises(ValueError):
        ChannelIdentityRef(provider="zalo_bot", account_key="k", external_id="")


def test_identity_ref_repr_redacts_external_ids():
    ref = _identity(external_id="PSID-1234567890")
    r = repr(ref)
    assert "PSID-1234567890" not in r
    # last 4 chars visible only — convenient for support without leaking PII
    assert "7890" in r


def test_account_ref_status_must_be_active_or_inactive():
    with pytest.raises(ValueError):
        ChannelAccountRef(
            id="id", provider="p", account_key="k", label="l", status="BANNED", generation=1
        )


def test_account_ref_generation_must_be_non_negative():
    with pytest.raises(ValueError):
        _account_ref(generation=-1)


def test_account_ref_is_active_helper():
    assert _account_ref(status=ChannelAccountStatus.ACTIVE).is_active
    assert not _account_ref(status=ChannelAccountStatus.INACTIVE).is_active


def test_account_ref_repr_redacts_account_key_not_label():
    ref = ChannelAccountRef(
        id="id-1",
        provider=PROVIDER_FACEBOOK_MESSENGER,
        account_key="page-secret-12345",
        label="Công ty ABC",
        status=ChannelAccountStatus.ACTIVE,
        generation=1,
    )
    r = repr(ref)
    assert "page-secret-12345" not in r
    # safe label is intentionally visible (it's the recruiter-facing name)
    assert "Công ty ABC" in r


# ─── inbound / outbound contracts ───────────────────────────────────────────


def test_inbound_message_requires_text():
    with pytest.raises(ValueError):
        ChannelInboundMessage(
            identity=_identity(),
            external_message_id="m1",
            text="",
            occurred_at=datetime.now(timezone.utc),
        )


def test_inbound_message_requires_external_message_id():
    with pytest.raises(ValueError):
        ChannelInboundMessage(
            identity=_identity(),
            external_message_id="",
            text="hi",
            occurred_at=datetime.now(timezone.utc),
        )


def test_inbound_message_repr_redacts_text_and_external_ids():
    msg = ChannelInboundMessage(
        identity=_identity(external_id="PSID-secret"),
        external_message_id="mid-secret-9999",
        text="sensitive candidate text with phone 0901234567",
        occurred_at=datetime.now(timezone.utc),
        trace_id="trace-1",
    )
    r = repr(msg)
    assert "sensitive candidate text" not in r
    assert "0901234567" not in r
    assert "mid-secret-9999" not in r
    assert "PSID-secret" not in r
    assert "text=<redacted>" in r


def test_outbound_command_requires_recipient_and_account_key():
    with pytest.raises(ValueError):
        OutboundTextCommand(
            provider="p", account_key="", recipient_id="r", text="t",
            channel_account_generation=1,
        )
    with pytest.raises(ValueError):
        OutboundTextCommand(
            provider="p", account_key="k", recipient_id="", text="t",
            channel_account_generation=1,
        )


def test_outbound_command_repr_redacts_recipient_and_text():
    cmd = OutboundTextCommand(
        provider=PROVIDER_FACEBOOK_MESSENGER,
        account_key="page-secret-key",
        recipient_id="PSID-recipient-secret",
        text="bot reply text",
        channel_account_generation=3,
    )
    r = repr(cmd)
    assert "page-secret-key" not in r
    assert "PSID-recipient-secret" not in r
    assert "bot reply text" not in r
    assert "text=<redacted>" in r
    # generation is internal authority metadata — safe and useful in logs
    assert "channel_account_generation=3" in r


# ─── send result / receipt ───────────────────────────────────────────────────


def test_send_result_is_send_unknown_uses_shared_taxonomy():
    # ambiguous transport → SEND_UNKNOWN
    assert ChannelSendResult(
        ok=False, error_class="read_timeout"
    ).is_send_unknown
    assert ChannelSendResult(
        ok=False, error_class="unknown"
    ).is_send_unknown

    # definite pre-send failure → retryable FAILED, not SEND_UNKNOWN
    assert not ChannelSendResult(
        ok=False, error_class="connect_error"
    ).is_send_unknown
    # provider-rejected envelope → retryable FAILED
    assert not ChannelSendResult(
        ok=False, error_class="provider_error"
    ).is_send_unknown


def test_send_result_suppressed_is_never_send_unknown():
    # even if the class is ambiguous, a suppression was deliberate
    result = ChannelSendResult(
        ok=False, error_class="unknown", suppressed=True
    )
    assert not result.is_send_unknown


def test_send_result_ok_is_never_send_unknown():
    assert not ChannelSendResult(ok=True, provider_message_id="mid").is_send_unknown


def test_send_result_repr_hides_error_text():
    # error text can echo a provider envelope; keep only the class
    result = ChannelSendResult(
        ok=False,
        error="provider said: invalid recipient PSID-1234567890",
        error_class="provider_error",
    )
    r = repr(result)
    assert "PSID-1234567890" not in r
    assert "invalid recipient" not in r
    assert "provider_error" in r


def test_send_result_requires_error_class_when_failed():
    """Every failure must be explicitly classified so the SEND_UNKNOWN vs
    FAILED decision cannot be silently dropped. A wrapper that forgets
    ``error_class`` on a failure would otherwise route to retryable FAILED —
    the opposite of the at-most-once bias. Construction refuses it.
    """
    with pytest.raises(ValueError, match="error_class is required"):
        ChannelSendResult(ok=False, error="connection broke mid-write")

    # suppressed results also require a class so the suppression reason is
    # explicit (policy_suppressed vs auth_revoked vs stale-authority)
    with pytest.raises(ValueError, match="error_class is required"):
        ChannelSendResult(ok=False, suppressed=True)

    # ok=True never needs a class (no failure to classify)
    assert ChannelSendResult(ok=True).ok


def test_receipt_validates_kind_and_scope():
    now = datetime.now(timezone.utc)
    receipt = ChannelReceipt(
        provider=PROVIDER_FACEBOOK_MESSENGER,
        account_key="page-111",
        provider_message_ids=("mid.1", "mid.2"),
        kind="delivered",
        occurred_at=now,
    )
    assert receipt.kind == "delivered"

    with pytest.raises(ValueError):
        ChannelReceipt(
            provider=PROVIDER_FACEBOOK_MESSENGER,
            account_key="page-111",
            provider_message_ids=("mid.1",),
            kind="bounced",
            occurred_at=now,
        )
    with pytest.raises(ValueError):
        ChannelReceipt(
            provider=PROVIDER_FACEBOOK_MESSENGER,
            account_key="page-111",
            provider_message_ids=(),
            kind="read",
            occurred_at=now,
        )


def test_receipt_repr_redacts_message_ids():
    r = repr(
        ChannelReceipt(
            provider=PROVIDER_FACEBOOK_MESSENGER,
            account_key="page-secret-page-id",
            provider_message_ids=("mid-secret-AAAA",),
            kind="read",
            occurred_at=datetime.now(timezone.utc),
        )
    )
    assert "mid-secret-AAAA" not in r
    assert "page-secret-page-id" not in r


# ─── registry: fail closed and capability lookup ─────────────────────────────


class _TextOnlyAdapter:
    """Adapter implementing only the required text port (no typing/receipt)."""

    provider = PROVIDER_ZALO_OA

    async def send_text(self, command: OutboundTextCommand) -> ChannelSendResult:
        return ChannelSendResult(ok=True, provider_message_id="oa-mid")


class _FullAdapter:
    """Adapter implementing text + typing + receipt capabilities."""

    provider = PROVIDER_ZALO_BOT

    async def send_text(self, command: OutboundTextCommand) -> ChannelSendResult:
        return ChannelSendResult(ok=True, provider_message_id="bot-mid")

    async def send_typing(
        self, *, account_key: str, recipient_id: str
    ) -> ChannelSendResult:
        return ChannelSendResult(ok=True)

    def parse_receipt(self, payload: dict) -> ChannelReceipt | None:
        return None


def test_registry_rejects_unknown_provider_id():
    class _Bad:
        provider = "telegram"  # not installed

        async def send_text(self, command):  # pragma: no cover - never called
            ...

    reg = ChannelAdapterRegistry()
    with pytest.raises(ValueError, match="unknown provider"):
        reg.register(_Bad())


def test_registry_fails_closed_for_missing_provider():
    reg = ChannelAdapterRegistry()
    assert reg.get(PROVIDER_ZALO_BOT) is None
    assert reg.get_typing(PROVIDER_ZALO_BOT) is None
    assert reg.get_receipt(PROVIDER_ZALO_BOT) is None
    assert reg.get("telegram") is None  # unknown provider also None


def test_registry_returns_text_adapter_for_registered_provider():
    reg = ChannelAdapterRegistry()
    adapter = _TextOnlyAdapter()
    reg.register(adapter)
    assert reg.get(PROVIDER_ZALO_OA) is adapter
    assert isinstance(adapter, TextChannelAdapter)


def test_registry_typing_capability_optional():
    reg = ChannelAdapterRegistry()
    reg.register(_FullAdapter())   # has typing
    reg.register(_TextOnlyAdapter())  # no typing
    assert reg.get_typing(PROVIDER_ZALO_BOT) is not None
    # OA adapter does not implement TypingCapability → None, not an error
    assert reg.get_typing(PROVIDER_ZALO_OA) is None


def test_registry_receipt_capability_optional():
    reg = ChannelAdapterRegistry()
    reg.register(_FullAdapter())
    reg.register(_TextOnlyAdapter())
    assert reg.get_receipt(PROVIDER_ZALO_BOT) is not None
    assert reg.get_receipt(PROVIDER_ZALO_OA) is None


def test_capability_protocols_are_runtime_checkable():
    """Business logic must be able to ask 'does this adapter support typing'
    via isinstance, not hasattr."""
    assert isinstance(_FullAdapter(), TypingCapability)
    assert isinstance(_FullAdapter(), ReceiptCapability)
    assert not isinstance(_TextOnlyAdapter(), TypingCapability)
    assert isinstance(_TextOnlyAdapter(), TextChannelAdapter)


# ─── account resolver: fail closed for inactive accounts ─────────────────────


async def test_resolver_returns_none_for_unknown_account():
    resolver = InMemoryAccountResolver()
    assert isinstance(resolver, ChannelAccountResolver)
    assert await resolver.resolve_active(
        provider=PROVIDER_FACEBOOK_MESSENGER, account_key="page-X"
    ) is None
    assert await resolver.resolve_any(
        provider=PROVIDER_FACEBOOK_MESSENGER, account_key="page-X"
    ) is None


async def test_resolver_resolve_active_fails_closed_for_inactive():
    """Inactive Page must not resolve send authority — only history reads."""
    resolver = InMemoryAccountResolver()
    inactive = _account_ref(
        account_key="page-archived", status=ChannelAccountStatus.INACTIVE
    )
    resolver.upsert(inactive)
    assert await resolver.resolve_active(
        provider=PROVIDER_FACEBOOK_MESSENGER, account_key="page-archived"
    ) is None
    # but resolve_any returns it so the inbox can render read-only history
    assert await resolver.resolve_any(
        provider=PROVIDER_FACEBOOK_MESSENGER, account_key="page-archived"
    ) is inactive


async def test_resolver_resolve_active_returns_active_account():
    resolver = InMemoryAccountResolver()
    active = _account_ref(account_key="page-active")
    resolver.upsert(active)
    assert await resolver.resolve_active(
        provider=PROVIDER_FACEBOOK_MESSENGER, account_key="page-active"
    ) is active


# ─── conformance: a future third provider fits the ports unchanged ───────────
#
# Red Team finding #15 proposed removing this test-only provider. The user
# rejected that finding: future Telegram/WhatsApp compatibility is an explicit
# requirement. This suite proves a brand-new text provider can implement the
# required port (plus optional capabilities) WITHOUT changing any shared
# contract — the guarantee Phase 3/5 rely on.

#: Synthetic provider id for the conformance double. NOT registered in
#: ``is_known_provider`` (this is a test-only adapter exercising the port
#: shape, not a production provider).
_FAKE_PROVIDER = "test_fake_text"


class _FakeFutureProvider:
    """Minimal text-only adapter for a hypothetical future provider.

    Implements :class:`TextChannelAdapter` structurally. The registry check
    below uses a local subclass that bypasses the installed-provider guard
    because this is a test fixture, not a production registration target.
    """

    provider = _FAKE_PROVIDER

    def __init__(self) -> None:
        self.sent: list[OutboundTextCommand] = []

    async def send_text(self, command: OutboundTextCommand) -> ChannelSendResult:
        self.sent.append(command)
        return ChannelSendResult(ok=True, provider_message_id=f"fake-{len(self.sent)}")


def test_future_provider_implements_required_text_port():
    """A brand-new provider can satisfy TextChannelAdapter with one method."""
    fake = _FakeFutureProvider()
    assert isinstance(fake, TextChannelAdapter)


async def test_future_provider_conforms_to_send_contract():
    """The conformance suite: build a command, send it, classify the result.

    This is the same flow Zalo wrappers (Phase 3) and the Messenger adapter
    (Phase 5) must pass. If this test breaks, the shared contract has drifted.
    """
    fake = _FakeFutureProvider()
    cmd = OutboundTextCommand(
        provider=_FAKE_PROVIDER,
        account_key="fake-account",
        recipient_id="fake-recipient",
        text="hello from the future provider",
        channel_account_generation=1,
    )
    result = await fake.send_text(cmd)

    assert isinstance(result, ChannelSendResult)
    assert result.ok
    assert result.provider_message_id is not None
    assert not result.is_send_unknown
    assert fake.sent == [cmd]


def test_future_provider_with_optional_capabilities_still_satisfies_text_port():
    """Adding typing/receipt to a future provider does not break text-port
    conformance — capabilities are additive, not mutating."""

    class _FakeWithCapabilities(_FakeFutureProvider):
        async def send_typing(self, *, account_key, recipient_id):
            return ChannelSendResult(ok=True)

        def parse_receipt(self, payload: dict) -> ChannelReceipt | None:
            return None

    fake = _FakeWithCapabilities()
    assert isinstance(fake, TextChannelAdapter)
    assert isinstance(fake, TypingCapability)
    assert isinstance(fake, ReceiptCapability)


# ─── diagnostic privacy sweep ────────────────────────────────────────────────
#
# Phase 1 privacy contract: no repr of a neutral type may leak candidate text,
# full external identifiers, or token-like keys. A stray repr() in a log line
# is the realistic failure mode we defend against.

_SENSITIVE_TOKEN_REGEX = re.compile(
    r"(EA[A-Z0-9]{20,}|gho_[A-Za-z0-9]{20,}|xox[bpoa]-[A-Za-z0-9-]{10,})"
)


def test_no_neutral_repr_leaks_full_external_ids():
    samples = [
        repr(_identity(external_id="PSID-1234567890")),
        repr(_account_ref(account_key="page-9876543210")),
        repr(
            ChannelInboundMessage(
                identity=_identity(external_id="PSID-1234567890"),
                external_message_id="mid-1234567890",
                text="x",
                occurred_at=datetime.now(timezone.utc),
            )
        ),
        repr(
            OutboundTextCommand(
                provider=PROVIDER_FACEBOOK_MESSENGER,
                account_key="page-1234567890",
                recipient_id="PSID-1234567890",
                text="x",
                channel_account_generation=1,
                reply_to_message_id="mid-1234567890",
            )
        ),
        repr(
            ChannelReceipt(
                provider=PROVIDER_FACEBOOK_MESSENGER,
                account_key="page-1234567890",
                provider_message_ids=("mid-1234567890",),
                kind="read",
                occurred_at=datetime.now(timezone.utc),
            )
        ),
    ]
    for s in samples:
        # full id never appears; only the masked suffix or a fixed mask does
        assert "1234567890" not in s, f"full id leaked in repr: {s}"
        assert not _SENSITIVE_TOKEN_REGEX.search(s), f"token-like value in repr: {s}"
