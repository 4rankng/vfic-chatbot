"""Canonical provider fallback rules for runtime persona selection."""

from __future__ import annotations

from types import SimpleNamespace

from app.graph.provider_scope import provider_from_conversation
from app.recruitment.domain.provider import (
    provider_from_conversation as recruitment_provider_from_conversation,
)


def test_provider_from_conversation_prefers_canonical_channel_identity() -> None:
    conversation = SimpleNamespace(
        channel_identity=SimpleNamespace(provider="facebook_messenger"),
        zalo_channel="oa",
    )

    assert provider_from_conversation(conversation) == "facebook_messenger"


def test_provider_from_conversation_falls_back_to_legacy_zalo_channel() -> None:
    assert provider_from_conversation(SimpleNamespace(channel_identity=None, zalo_channel="oa")) == "zalo_oa"
    assert provider_from_conversation(SimpleNamespace(channel_identity=None, zalo_channel="bot")) == "zalo_bot"


def test_graph_provider_scope_reexports_recruitment_policy() -> None:
    assert provider_from_conversation is recruitment_provider_from_conversation
