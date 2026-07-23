"""Single candidate extraction pipeline.

One LLM call returns both structured CRM lead fields and memory facts. `leads`
remains the canonical UI/profile store; `memories` remains recall context.
"""

from __future__ import annotations

import logging
from typing import Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.text import normalize_vietnamese_text
from app.models.conversation import ConversationMode, ConversationStatus
from app.models.lead import Lead
from app.prompts.candidate_extraction import CANDIDATE_EXTRACT_SYSTEM_PROMPT
from app.recruitment.application.candidate_extraction import (
    CandidateExtractionUseCases,
    candidate_turn as _candidate_turn,
)
from app.recruitment.domain.candidate_extraction import CandidateExtraction, ContactIntent
from app.services.lead.events import LeadEventBus
from app.services.lead.normalizers import extract_self_reported_name, normalize_lead
from app.services.lead.repository import LeadRepository
from app.services.memory_service import (
    BatchEmbedder,
    MemoryService,
    greeting_gate,
    parse_memory_facts,
)

Extractor = Callable[[str, str], Awaitable[str]]

logger = logging.getLogger(__name__)


class _LegacyCandidateLeadNormalizer:
    def normalize_lead_patch(self, value: object, chat_id: str) -> dict[str, object] | None:
        return normalize_lead(value, chat_id)

    def extract_self_reported_name(
        self,
        text: str | None,
        *,
        prev_bot_message: str | None = None,
    ) -> str | None:
        return extract_self_reported_name(text, prev_bot_message=prev_bot_message)


def _candidate_extraction_use_cases() -> CandidateExtractionUseCases:
    return CandidateExtractionUseCases(
        normalizer=_LegacyCandidateLeadNormalizer(),
        parse_memory_facts=parse_memory_facts,
        normalize_text=normalize_vietnamese_text,
    )


def has_explicit_human_review_evidence(user_text: str, intent: ContactIntent) -> bool:
    return _candidate_extraction_use_cases().has_explicit_human_review_evidence(
        user_text,
        intent,
    )


def candidate_turn(
    user_text: str,
    bot_output: str,
    *,
    existing_notes: str | None = None,
    oa_profile_display_name: str | None = None,
) -> str:
    return _candidate_turn(
        user_text,
        bot_output,
        existing_notes=existing_notes,
        oa_profile_display_name=oa_profile_display_name,
    )


class CandidateExtractionService:
    @staticmethod
    async def persist_explicit_name(
        db: AsyncSession,
        chat_id: str,
        user_text: str,
        *,
        prev_bot_message: str | None = None,
    ) -> str | None:
        """Persist an unambiguous self-introduced name on the inbound path.

        This intentionally does not wait for the deferred LLM extraction job.
        The latter still enriches the rest of the candidate profile and can
        overwrite this value only when it has a non-empty extracted name.

        ``prev_bot_message`` is the bot's immediately preceding reply; when it
        asked for the name, a bare reply ("Dũng") is captured here so the next
        turn personalises correctly instead of reverting to the Zalo profile
        name.
        """
        resolved = _candidate_extraction_use_cases().resolve_explicit_name(
            chat_id=chat_id,
            user_text=user_text,
            prev_bot_message=prev_bot_message,
        )
        if resolved is None:
            return None
        await CandidateExtractionService.upsert_lead(db, resolved.lead_patch)
        return resolved.value

    @staticmethod
    async def extract(
        extractor: Extractor,
        user_text: str,
        bot_output: str,
        chat_id: str,
        *,
        existing_notes: str | None = None,
        oa_profile_display_name: str | None = None,
    ) -> CandidateExtraction:
        result = await _candidate_extraction_use_cases().extract(
            extractor,
            system_prompt=CANDIDATE_EXTRACT_SYSTEM_PROMPT,
            user_text=user_text,
            bot_output=bot_output,
            chat_id=chat_id,
            existing_notes=existing_notes,
            oa_profile_display_name=oa_profile_display_name,
        )
        logger.debug(
            "candidate extract: lead=%s memory_facts=%d intent=%s confidence=%.2f "
            "from user text (%d chars)",
            bool(result.lead_patch),
            len(result.memory_facts),
            result.contact_intent,
            result.intent_confidence,
            len(user_text or ""),
        )
        return result

    @staticmethod
    async def upsert_lead(db: AsyncSession, lead_patch: dict | None) -> int | None:
        if not lead_patch:
            return None
        lead_id = await LeadRepository(db).upsert(lead_patch)
        if lead_id is None:
            return None
        await db.commit()
        saved = await db.get(Lead, lead_id)
        if saved is not None:
            await LeadEventBus().lead_updated(saved)
        return lead_id

    @staticmethod
    async def persist(
        db: AsyncSession,
        embed_batch: BatchEmbedder,
        extractor: Extractor,
        chat_id: str,
        user_text: str,
        bot_output: str,
        *,
        expected_conversation_version: int | None = None,
    ) -> CandidateExtraction:
        if not greeting_gate(user_text):
            logger.debug("candidate extraction skipped by greeting_gate")
            return CandidateExtraction(lead_patch=None, memory_facts=[])

        from app.services.conversation import ConversationService

        conversation_service = ConversationService(db)
        conversation = await conversation_service.get_by_zalo(chat_id)
        if conversation is not None and (
            conversation.mode == ConversationMode.HUMAN
            or conversation.status == ConversationStatus.CLOSED
            or (
                expected_conversation_version is not None
                and conversation.version != expected_conversation_version
            )
        ):
            logger.debug("candidate extraction skipped because source turn is no longer current")
            return CandidateExtraction(lead_patch=None, memory_facts=[])

        existing_lead = await LeadRepository(db).by_zalo_id(chat_id)
        existing_notes = existing_lead.get("notes") if existing_lead else None
        oa_profile_display_name = None
        if (
            chat_id.startswith("oa:")
            and conversation is not None
            and conversation.contact is not None
            and not str((existing_lead or {}).get("name") or "").strip()
        ):
            oa_profile_display_name = conversation.contact.display_name
        result = await CandidateExtractionService.extract(
            extractor,
            user_text,
            bot_output,
            chat_id,
            existing_notes=existing_notes,
            oa_profile_display_name=oa_profile_display_name,
        )

        if result.requires_human_review:
            if not has_explicit_human_review_evidence(user_text, result.contact_intent):
                logger.info(
                    "candidate extraction escalation ignored without explicit evidence intent=%s",
                    result.contact_intent,
                )
                return CandidateExtraction(
                    lead_patch=None,
                    memory_facts=[],
                    contact_intent="uncertain",
                    intent_confidence=0.0,
                )
            if conversation is not None and expected_conversation_version is not None:
                await conversation_service.escalate_extracted_intent(
                    conversation,
                    reason=result.contact_intent,
                    confidence=result.intent_confidence,
                    expected_version=expected_conversation_version,
                )
            return result

        await CandidateExtractionService.upsert_lead(db, result.lead_patch)

        if result.memory_facts:
            try:
                await MemoryService.save(db, embed_batch, chat_id, result.memory_facts)
            except Exception:
                logger.warning(
                    "memory fact save failed for chat %s (%d facts extracted); chat turn continues",
                    chat_id,
                    len(result.memory_facts),
                    exc_info=True,
                )

        return result
