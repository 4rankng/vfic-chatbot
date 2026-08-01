"""Canonical provider fallback rules for runtime persona selection."""

from __future__ import annotations

from types import SimpleNamespace

from app.recruitment.domain.provider import (
    provider_from_conversation,
    recipient_from_conversation,
)


def test_provider_from_conversation_prefers_canonical_channel_identity() -> None:
    conversation = SimpleNamespace(
        channel_identity=SimpleNamespace(provider="facebook_messenger"),
        zalo_channel="oa",
    )

    assert provider_from_conversation(conversation) == "facebook_messenger"


def test_recipient_from_conversation_uses_messenger_canonical_identity() -> None:
    conversation = SimpleNamespace(
        channel_identity=SimpleNamespace(
            provider="facebook_messenger",
            external_id="psid-1",
        ),
        zalo_channel="facebook_messenger",
        zalo_chat_id=None,
    )

    assert recipient_from_conversation(conversation) == "psid-1"


def test_provider_from_conversation_falls_back_to_legacy_zalo_channel() -> None:
    assert provider_from_conversation(SimpleNamespace(channel_identity=None, zalo_channel="oa")) == "zalo_oa"
    assert provider_from_conversation(SimpleNamespace(channel_identity=None, zalo_channel="bot")) == "zalo_bot"
