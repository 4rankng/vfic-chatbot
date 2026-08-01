"""Provider-neutral persona scope resolution for recruitment policies."""

from __future__ import annotations

from typing import Protocol


class ChannelIdentityView(Protocol):
    provider: str | None
    external_id: str | None


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


def recipient_from_conversation(conversation: ConversationProviderView) -> str | None:
    """Resolve the provider recipient while preserving Zalo compatibility aliases."""

    if provider_from_conversation(conversation) == "facebook_messenger":
        identity = getattr(conversation, "channel_identity", None)
        external_id = getattr(identity, "external_id", None)
        return str(external_id) if external_id else None
    zalo_chat_id = getattr(conversation, "zalo_chat_id", None)
    return str(zalo_chat_id) if zalo_chat_id else None


__all__ = [
    "ConversationProviderView",
    "SUPPORTED_CONVERSATION_PROVIDERS",
    "provider_from_conversation",
    "recipient_from_conversation",
]
