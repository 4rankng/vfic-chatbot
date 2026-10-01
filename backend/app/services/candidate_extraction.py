"""Single candidate extraction pipeline.

One LLM call returns both structured CRM lead fields and memory facts. `leads`
remains the canonical UI/profile store; `memories` remains recall context.
"""

from __future__ import annotations

import logging
import uuid
from typing import Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.domain.text import normalize_vietnamese_text
from app.models.conversation import Conversation, ConversationMode, ConversationStatus
from app.models.lead import Lead
from app.prompts.candidate_extraction import CANDIDATE_EXTRACT_SYSTEM_PROMPT
from app.recruitment.application.candidate_extraction import (
    CandidateExtractionUseCases,
    candidate_turn as _candidate_turn,
)
from app.recruitment.domain.candidate_extraction import CandidateExtraction, ContactIntent
from app.recruitment.domain.intake import candidate_contact_mobile, candidate_wish
from app.recruitment.domain.provider import lead_key_for_chat, lead_key_for_conversation
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


def _tingting_oa_conversation(conversation) -> bool:
    """Whether the conversation sits on the TingTing support OA.

    Operator rule 2026-09-29: nobody works that OA as a human, so the post-send
    human-review escalation must never park one of its threads in a queue
    nobody watches. Identity-only check, mirroring the graph-layer
    ``lanes._tingting_account_conversation`` (services never import the graph
    package, so the two-line identity read is duplicated, not shared).
    """
    from app.channels.types import PROVIDER_ZALO_OA, TINGTING_OA_ACCOUNT_KEY

    identity = getattr(conversation, "channel_identity", None)
    if identity is None or str(getattr(identity, "provider", "") or "") != PROVIDER_ZALO_OA:
        return False
    return str(getattr(identity, "account_key", "") or "") == TINGTING_OA_ACCOUNT_KEY


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
        The deferred extractor still enriches the rest of the candidate profile,
        while the persistence boundary protects this confirmed identity.

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
        try:
            result = await _candidate_extraction_use_cases().extract(
                extractor,
                system_prompt=CANDIDATE_EXTRACT_SYSTEM_PROMPT,
                user_text=user_text,
                bot_output=bot_output,
                chat_id=chat_id,
                existing_notes=existing_notes,
                oa_profile_display_name=oa_profile_display_name,
            )
        except Exception as exc:
            explicit = {
                "name": extract_self_reported_name(user_text),
                "phone": candidate_contact_mobile(user_text),
                "desired_job": candidate_wish(user_text),
            }
            if not any(explicit.values()):
                raise
            logger.warning(
                "candidate extractor unavailable; preserving explicit contact evidence error_type=%s",
                type(exc).__name__,
            )
            result = CandidateExtraction(
                lead_patch=normalize_lead(explicit, chat_id),
                memory_facts=[],
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
    async def upsert_lead(
        db: AsyncSession,
        lead_patch: dict | None,
        *,
        contact_id: str | None = None,
    ) -> int | None:
        if not lead_patch:
            return None
        repo = LeadRepository(db)
        lead_id = (
            await repo.upsert_by_contact(contact_id, lead_patch)
            if contact_id
            else await repo.upsert(lead_patch)
        )
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
        contact_id: str | None = None,
        conversation_id: str | None = None,
    ) -> CandidateExtraction:
        if not greeting_gate(user_text):
            logger.debug("candidate extraction skipped by greeting_gate")
            return CandidateExtraction(lead_patch=None, memory_facts=[])

        from app.services.conversation import ConversationService

        conversation_service = ConversationService(db)
        if conversation_id:
            # A Messenger row has zalo_chat_id IS NULL, so get_by_zalo never
            # finds it. Loading by primary key is authoritative and lets the
            # HUMAN/CLOSED guard below actually run for those turns.
            conversation = await db.get(Conversation, uuid.UUID(str(conversation_id)))
        else:
            conversation = await conversation_service.get_by_zalo(chat_id)
        # ``expected_conversation_version`` is deliberately NOT compared here.
        # The persist job is enqueued after record_bot_outcome, which bumps
        # Conversation.version as part of completing the very turn the job
        # describes — so the captured turn-start version is already stale at
        # enqueue time and the comparison rejected every live extraction while
        # still reporting the job as "Successfully completed". It also has to
        # stay out: each job's patch holds only what its own turn revealed, so
        # skipping superseded turns would silently drop a phone number given on
        # turn 3 because turn 50 arrived later. Ordering is what keeps the
        # newest patch last (the queue is FIFO on a single worker), and
        # upsert_lead merges field-wise, never clearing a value. The version is
        # still passed through to escalate_extracted_intent, which needs it as
        # an optimistic-concurrency token.
        if conversation is not None and (
            conversation.mode == ConversationMode.HUMAN
            or conversation.status == ConversationStatus.CLOSED
        ):
            logger.info(
                "candidate extraction skipped: conversation is %s for chat %s",
                "human-owned"
                if conversation.mode == ConversationMode.HUMAN
                else "closed",
                chat_id,
            )
            return CandidateExtraction(lead_patch=None, memory_facts=[])

        lead_key = (
            lead_key_for_conversation(conversation)
            if conversation is not None
            else lead_key_for_chat(chat_id, contact_id=contact_id)
        )

        # One key decides both the read and the write, so a turn can never read
        # one lead and write another. The zalo branch keeps the Zalo/OA rows
        # (and the leads_zalo_id_fkey they satisfy) exactly as they were; every
        # other provider is contact-keyed, with no per-provider branch.
        lead_repo = LeadRepository(db)
        if lead_key.zalo_id:
            existing_lead = await lead_repo.by_zalo_id(lead_key.zalo_id)
        elif lead_key.contact_id:
            existing_lead = await lead_repo.by_contact_id(lead_key.contact_id)
        else:
            logger.warning(
                "candidate extraction has no lead key for chat %s; skipping lead write",
                chat_id,
            )
            existing_lead = None
        existing_notes = existing_lead.get("notes") if existing_lead else None
        existing_name = str((existing_lead or {}).get("name") or "").strip()
        oa_profile_display_name = None
        if (
            chat_id.startswith("oa:")
            and conversation is not None
            and conversation.contact is not None
            and not existing_name
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
        if result.lead_patch and result.lead_patch.get("name"):
            # Canonical identity never comes from a deferred model guess. This
            # also closes the race where a recruiter or the inbound explicit-name
            # path writes while extraction is awaiting the model.
            result.lead_patch["name"] = extract_self_reported_name(user_text)

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
                # Operator rule 2026-09-29: nobody works the TingTing OA as a
                # human, so the bot's replies there already point the employee
                # at the hotline and this escalation must never park the thread
                # in a queue no one watches.
                if _tingting_oa_conversation(conversation):
                    logger.info(
                        "candidate extraction escalation skipped: the TingTing "
                        "OA never escalates for chat %s",
                        chat_id,
                    )
                else:
                    await conversation_service.escalate_extracted_intent(
                        conversation,
                        reason=result.contact_intent,
                        confidence=result.intent_confidence,
                        expected_version=expected_conversation_version,
                    )
            return result

        if lead_key.is_writable:
            await CandidateExtractionService.upsert_lead(
                db,
                result.lead_patch,
                contact_id=None if lead_key.is_zalo_keyed else lead_key.contact_id,
            )

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
