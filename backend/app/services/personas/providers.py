"""Canonical adapter-provider helpers for persona assignment and resolution."""

from __future__ import annotations

from app.graph.provider_scope import provider_from_conversation
from app.schemas.personas import AdapterProvider, SUPPORTED_ADAPTER_PROVIDERS

_PROVIDER_LABELS: dict[AdapterProvider, str] = {
    "zalo_bot": "Zalo Bot",
    "zalo_oa": "Zalo OA",
    "facebook_messenger": "Facebook Messenger",
}


def validate_adapter_provider(provider: str) -> AdapterProvider:
    normalized = (provider or "").strip()
    if normalized not in SUPPORTED_ADAPTER_PROVIDERS:
        raise ValueError(f"Unsupported adapter provider: {provider}")
    return normalized  # type: ignore[return-value]


def adapter_provider_label(provider: AdapterProvider) -> str:
    return _PROVIDER_LABELS[provider]


def conversation_adapter_provider(conversation) -> AdapterProvider:
    return provider_from_conversation(conversation)  # type: ignore[return-value]
