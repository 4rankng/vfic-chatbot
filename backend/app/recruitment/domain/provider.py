"""Provider-neutral persona scope resolution for recruitment policies."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class ChannelIdentityView(Protocol):
    provider: str | None
    external_id: str | None


class ConversationProviderView(Protocol):
    channel_identity: ChannelIdentityView | None
    zalo_channel: str | None


@dataclass(frozen=True, slots=True)
class LeadKey:
    """Which lead row a conversation writes to, resolved provider-neutrally.

    Alembic 0047 made ``leads.contact_id`` the canonical key and left
    ``leads.zalo_id`` as a Zalo-only compatibility alias. That asymmetry is a
    property of the providers, not of any one of them, so it is resolved once
    here instead of being re-derived as a ``zalo_chat_id IS NULL`` test at
    every call site. Installing a new provider therefore needs no new branch:
    unless its conversation carries a Zalo chat id, the lead is contact-keyed.

    ``zalo_id`` is only a key when the conversation row actually holds that
    chat id, because ``leads_zalo_id_fkey`` points at
    ``conversations(zalo_chat_id)``.
    """

    contact_id: str | None = None
    zalo_id: str | None = None

    @property
    def is_zalo_keyed(self) -> bool:
        return self.zalo_id is not None

    @property
    def is_writable(self) -> bool:
        """True when the key can address a lead row on its own."""
        return self.zalo_id is not None or self.contact_id is not None


def lead_key_for_conversation(conversation: ConversationProviderView) -> LeadKey:
    """The lead key for a loaded conversation row."""

    contact_id = getattr(conversation, "contact_id", None)
    zalo_chat_id = getattr(conversation, "zalo_chat_id", None)
    return LeadKey(
        contact_id=str(contact_id) if contact_id else None,
        zalo_id=str(zalo_chat_id) if zalo_chat_id else None,
    )


def lead_key_for_chat(chat_id: str, *, contact_id: str | None = None) -> LeadKey:
    """The lead key for a chat id whose conversation row is not loaded.

    A caller that already resolved the contact is authoritative: the chat id
    of a contact-keyed provider (a PSID, or a future platform's recipient id)
    is a provider recipient, NOT a ``conversations.zalo_chat_id``, so it must
    never be offered to ``leads.zalo_id`` — that is precisely what violated
    ``leads_zalo_id_fkey``. Only the Zalo/OA inbound path, which holds a real
    ``zalo_chat_id`` and no contact, keys on the chat id itself.
    """

    if contact_id:
        return LeadKey(contact_id=str(contact_id))
    return LeadKey(zalo_id=chat_id or None)


def lead_key_for_row(lead: dict | None) -> LeadKey | None:
    """The key a stored lead row is addressed by, or None when there is no row.

    Read from the row itself rather than from the provider, so a write that
    targets an existing lead always targets the key that lead is stored under —
    including legacy rows written before the canonical key existed.
    """

    if not lead or lead.get("id") is None:
        return None
    contact_id = lead.get("contact_id")
    zalo_id = str(lead.get("zalo_id") or "").strip()
    return LeadKey(
        contact_id=str(contact_id) if contact_id else None,
        zalo_id=zalo_id or None,
    )


SUPPORTED_CONVERSATION_PROVIDERS = frozenset({"zalo_bot", "zalo_oa", "facebook_messenger"})


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
    "LeadKey",
    "SUPPORTED_CONVERSATION_PROVIDERS",
    "lead_key_for_chat",
    "lead_key_for_conversation",
    "lead_key_for_row",
    "provider_from_conversation",
    "recipient_from_conversation",
]
