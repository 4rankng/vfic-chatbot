"""Composition helpers for recruitment application ports."""

from __future__ import annotations

from app.recruitment.application.ports import (
    FollowupEligibilityPort,
    LeadContextQueryPort,
    LeadGenderPort,
    ProactiveStatePort,
)
from app.recruitment.application.persistence import (
    PersistCandidateCommand,
    persist_candidate,
)
from app.recruitment.infrastructure.service_adapters import (
    ServiceCandidatePersistenceAdapter,
    ServiceFollowupEligibilityAdapter,
    ServiceLeadContextAdapter,
    ServiceLeadGenderAdapter,
    ServiceProactiveStateAdapter,
)


def build_lead_context(db) -> LeadContextQueryPort:
    return ServiceLeadContextAdapter(db)


def build_lead_gender(db) -> LeadGenderPort:
    return ServiceLeadGenderAdapter(db)


def build_followup_eligibility(db) -> FollowupEligibilityPort:
    return ServiceFollowupEligibilityAdapter(db)


def build_proactive_state(db) -> ProactiveStatePort:
    return ServiceProactiveStateAdapter(db)


async def run_candidate_persistence(
    db,
    *,
    embed_batch,
    extractor,
    chat_id: str,
    user_text: str,
    bot_output: str,
    expected_conversation_version: int | None,
    contact_id: str | None = None,
    conversation_id: str | None = None,
):
    return await persist_candidate(
        ServiceCandidatePersistenceAdapter(db),
        PersistCandidateCommand(
            chat_id=chat_id,
            user_text=user_text,
            bot_output=bot_output,
            expected_conversation_version=expected_conversation_version,
            contact_id=contact_id,
            conversation_id=conversation_id,
        ),
        embed_batch=embed_batch,
        extractor=extractor,
    )


__all__ = [
    "build_followup_eligibility",
    "build_lead_context",
    "build_lead_gender",
    "build_proactive_state",
    "run_candidate_persistence",
]
