"""Provider-neutral persona scope resolution for recruitment policies."""

from __future__ import annotations

from typing import Protocol


class ChannelIdentityView(Protocol):
    provider: str | None


class ConversationProviderView(Protocol):
    channel_identity: ChannelIdentityView | None
    zalo_channel: str | None


SUPPORTED_CONVERSATION_PROVIDERS = frozenset(
    {"zalo_bot", "zalo_oa", "facebook_messenger"}
)


def provider_from_conversation(conversation: ConversationProviderView) -> str:
    """Resolve the canonical provider while preserving legacy channel fallback."""

    identity = getattr(conversation, "channel_identity", None)
    provider = getattr(identity, "provider", None)
    if provider in SUPPORTED_CONVERSATION_PROVIDERS:
        return provider

    fallback = str(getattr(conversation, "zalo_channel", "") or "").strip()
    if fallback == "oa":
        return "zalo_oa"
    if fallback == "facebook_messenger":
        return "facebook_messenger"
    return "zalo_bot"


__all__ = [
    "ConversationProviderView",
    "SUPPORTED_CONVERSATION_PROVIDERS",
    "provider_from_conversation",
]
