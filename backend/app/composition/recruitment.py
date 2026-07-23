"""Composition helpers for recruitment application ports."""

from __future__ import annotations

from app.recruitment.application.ports import (
    FollowupEligibilityPort,
    LeadContextQueryPort,
    ProactiveStatePort,
)
from app.recruitment.application.persistence import (
    PersistCandidateCommand,
    persist_candidate,
)
from app.recruitment.infrastructure.legacy_adapters import (
    LegacyCandidatePersistenceAdapter,
    LegacyFollowupEligibilityAdapter,
    LegacyLeadContextAdapter,
    LegacyProactiveStateAdapter,
)


def build_lead_context(db) -> LeadContextQueryPort:
    return LegacyLeadContextAdapter(db)


def build_followup_eligibility(db) -> FollowupEligibilityPort:
    return LegacyFollowupEligibilityAdapter(db)


def build_proactive_state(db) -> ProactiveStatePort:
    return LegacyProactiveStateAdapter(db)


async def run_candidate_persistence(
    db,
    *,
    embed_batch,
    extractor,
    chat_id: str,
    user_text: str,
    bot_output: str,
    expected_conversation_version: int | None,
):
    return await persist_candidate(
        LegacyCandidatePersistenceAdapter(db),
        PersistCandidateCommand(
            chat_id=chat_id,
            user_text=user_text,
            bot_output=bot_output,
            expected_conversation_version=expected_conversation_version,
        ),
        embed_batch=embed_batch,
        extractor=extractor,
    )


__all__ = [
    "build_followup_eligibility",
    "build_lead_context",
    "build_proactive_state",
    "run_candidate_persistence",
]
