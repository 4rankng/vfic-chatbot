"""Closed setup choices backed by implemented platform contracts."""

from __future__ import annotations


INTEGRATION_REFERENCE_REQUIREMENTS: dict[str, tuple[str, ...]] = {
    "minimax": ("minimax_api_key", "minimax_enable"),
    "openrouter": ("openrouter_api_key", "openrouter_enable"),
    "zalo": ("zalo_bot_token", "zalo_bot_webhook_secret"),
}
INTEGRATION_REFERENCE_ENABLE_KEYS = {
    "minimax": "minimax_enable",
    "openrouter": "openrouter_enable",
}

CHAT_INTEGRATION_REFERENCES = frozenset({"minimax", "openrouter"})
EMBEDDING_INTEGRATION_REFERENCES = frozenset({"openrouter"})
HANDOFF_MODES = ("manual", "assisted", "automatic")
AUTHENTICATION_METHODS = ("email_password",)


def integration_reference_ids() -> tuple[str, ...]:
    return tuple(sorted(INTEGRATION_REFERENCE_REQUIREMENTS))
