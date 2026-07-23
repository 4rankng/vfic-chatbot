"""Framework-free ports for recruitment context and decision queries."""

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
    """Resolve the active persona body for one adapter/provider scope."""

    async def active_persona_body(self, provider: str | None = None) -> str | None: ...


class LeadContextQueryPort(Protocol):
    """Candidate-profile context consumed by the agent runtime."""

    async def profile_text(self, chat_id: str) -> str: ...

    async def context(
        self,
        chat_id: str,
        current_user_text: str,
        recent_messages: list[Any],
    ) -> tuple[str, str]: ...

    def instruction(self, question: str) -> str: ...


class RecommendationQueryPort(Protocol):
    """Neutral recruitment reads over projected active-job authority."""

    async def match_jobs_for_lead(
        self,
        chat_id: str,
        *,
        top_k: int = 5,
        province: str | None = None,
    ) -> list[Any]: ...

    async def recommend_jobs_for_lead(
        self,
        chat_id: str,
        *,
        top_k: int = 5,
        province: str | None = None,
    ) -> Any: ...

    async def list_active_jobs(
        self,
        *,
        project_slug: str | None = None,
        role: str | None = None,
        company: str | None = None,
        location: str | None = None,
        top_k: int = 3,
        sort_by: str | None = None,
    ) -> Any: ...


class FollowupEligibilityPort(Protocol):
    """Final per-conversation recruitment follow-up decision."""

    async def allowed(self, conversation: Any) -> tuple[bool, str]: ...


__all__ = [
    "ConversationAdapterProviderResolver",
    "FollowupEligibilityPort",
    "LeadContextQueryPort",
    "PersonaBodyResolver",
    "PersonaFollowupRulesResolver",
    "RecommendationQueryPort",
]
