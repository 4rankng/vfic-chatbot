"""Pure helpers for canonical provider selection inside graph/runtime code."""

from __future__ import annotations


def provider_from_conversation(conversation) -> str:
    identity = getattr(conversation, "channel_identity", None)
    provider = getattr(identity, "provider", None)
    if provider in {"zalo_bot", "zalo_oa", "facebook_messenger"}:
        return provider

    fallback = str(getattr(conversation, "zalo_channel", "") or "").strip()
    if fallback == "oa":
        return "zalo_oa"
    if fallback == "facebook_messenger":
        return "facebook_messenger"
    return "zalo_bot"
