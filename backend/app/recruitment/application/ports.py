"""Framework-free ports for recruitment persona and follow-up resolution."""

from __future__ import annotations

from typing import Any, Protocol

from app.recruitment.domain.proactive import FollowupRulesPolicy


class ConversationAdapterProviderResolver(Protocol):
    """Resolve the canonical adapter/provider scope for one conversation."""

    def resolve_adapter_provider(self, conversation: Any) -> str: ...


class PersonaFollowupRulesResolver(Protocol):
    """Load the effective follow-up rules for one adapter/provider scope."""

    async def followup_rules_for_provider(self, provider: str) -> FollowupRulesPolicy: ...


class PersonaBodyResolver(Protocol):
    """Resolve the effective active persona body for one adapter/provider scope."""

    async def active_persona_body(self, provider: str | None = None) -> str | None: ...


__all__ = [
    "ConversationAdapterProviderResolver",
    "PersonaBodyResolver",
    "PersonaFollowupRulesResolver",
]
