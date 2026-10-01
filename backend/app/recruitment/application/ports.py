"""Framework-free ports for recruitment context and decision queries."""

from __future__ import annotations

from typing import Any, Protocol

from app.recruitment.application.lead_lookup import (
    LeadLookup,
    LeadRecord,
    UNRESOLVED_LEAD,
)
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
    """Candidate-profile context consumed by the agent runtime.

    Omit ``lead`` to resolve it; an explicit None is a completed lookup miss.
    """

    async def profile_text(self, chat_id: str, contact_id: str | None = None) -> str: ...

    async def context(
        self,
        chat_id: str,
        current_user_text: str,
        recent_messages: list[Any],
        contact_id: str | None = None,
        *,
        lead: LeadLookup = UNRESOLVED_LEAD,
    ) -> tuple[str, str]: ...

    def instruction(self, question: str) -> str: ...


class FollowupEligibilityPort(Protocol):
    """Final per-conversation recruitment follow-up decision."""

    async def allowed(self, conversation: Any) -> tuple[bool, str]: ...


class LeadGenderPort(Protocol):
    """Candidate gender memory shared by the decision hop and the lead record.

    ``stored_gender`` returns whatever non-blank value the lead carries (canonical
    or not) so a turn never re-judges a value a human or a provider already set.
    ``record_inferred_gender`` fills a blank only unless ``override`` is set, which
    the runner uses when the candidate explicitly self-refers in the current
    message — the candidate's own word outranks an earlier inference.

    ``contact_id`` is the fallback key for Messenger, whose leads are keyed by
    contact with a NULL ``zalo_id`` (migration 0047) and so are invisible to a
    chat-id lookup.

    ``resolve_lead`` owns the turn's initial read. Its result, including None,
    is reused through ``lead`` until a successful mutation requires a refresh;
    omitting the keyword retains the fallback for independent callers.
    """

    async def resolve_lead(
        self, chat_id: str, contact_id: str | None = None
    ) -> LeadRecord | None: ...

    async def stored_gender(
        self,
        chat_id: str,
        contact_id: str | None = None,
        *,
        lead: LeadLookup = UNRESOLVED_LEAD,
    ) -> str: ...

    async def record_inferred_gender(
        self,
        chat_id: str,
        gender: str,
        *,
        contact_id: str | None = None,
        override: bool = False,
        lead: LeadLookup = UNRESOLVED_LEAD,
    ) -> bool: ...

    async def record_profile_name(
        self,
        chat_id: str,
        name: str,
        *,
        contact_id: str | None = None,
        lead: LeadLookup = UNRESOLVED_LEAD,
    ) -> bool: ...


class ProactiveStatePort(Protocol):
    """Persistence seam used by graph proactive orchestration."""

    async def refresh(self, conversation: Any) -> None: ...

    async def flush(self) -> None: ...

    async def commit(self) -> None: ...

    async def has_worker_reply_since(
        self,
        conversation_id: Any,
        since: Any,
    ) -> bool: ...

    async def opt_out_for_silence(self, conversation: Any) -> None: ...

    async def stamp_attempt(self, conversation: Any, attempted_at: Any) -> None: ...


__all__ = [
    "ConversationAdapterProviderResolver",
    "FollowupEligibilityPort",
    "LeadContextQueryPort",
    "LeadGenderPort",
    "PersonaBodyResolver",
    "PersonaFollowupRulesResolver",
    "ProactiveStatePort",
]
