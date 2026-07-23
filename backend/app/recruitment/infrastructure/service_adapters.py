"""Adapters over the established recruitment persistence services."""

from __future__ import annotations


class ServiceLeadContextAdapter:
    """Lead-context query adapter preserving the established prompt behavior."""

    def __init__(self, db) -> None:
        self._db = db

    async def profile_text(self, chat_id: str) -> str:
        from app.services.lead import lead_profile_text
        from app.services.lead.repository import LeadRepository

        lead = await LeadRepository(self._db).by_zalo_id(chat_id)
        return lead_profile_text(lead)

    async def context(self, chat_id, current_user_text, recent_messages):
        from app.services.conversation import ConversationService
        from app.services.lead import lead_profile_text
        from app.services.lead.probing import (
            lead_collection_question,
            oa_profile_name_guidance,
        )
        from app.services.lead.repository import LeadRepository

        lead = await LeadRepository(self._db).by_zalo_id(chat_id)
        oa_profile_display_name = None
        if chat_id.startswith("oa:"):
            conversation = await ConversationService(self._db).get_by_zalo(chat_id)
            if conversation is not None and conversation.contact is not None:
                oa_profile_display_name = conversation.contact.display_name

        collection_lead = lead
        if oa_profile_display_name and not str((lead or {}).get("name") or "").strip():
            collection_lead = dict(lead or {})
            collection_lead["name"] = oa_profile_display_name
            next_question = lead_collection_question(
                lead=collection_lead,
                current_user_text=current_user_text,
                recent_messages=recent_messages,
            )
            collection_guidance = oa_profile_name_guidance(
                oa_profile_display_name,
                next_question=next_question,
            )
        else:
            collection_guidance = lead_collection_question(
                lead=lead,
                current_user_text=current_user_text,
                recent_messages=recent_messages,
            )
        return (
            lead_profile_text(
                lead,
                oa_profile_display_name=oa_profile_display_name,
                personalize=chat_id.startswith("oa:"),
            ),
            collection_guidance,
        )

    def instruction(self, question: str) -> str:
        from app.services.lead.probing import lead_collection_instruction

        return lead_collection_instruction(question=question)


class ServiceFollowupEligibilityAdapter:
    """Follow-up decision adapter preserving provider rules and reason codes."""

    def __init__(self, db) -> None:
        self._db = db

    async def allowed(self, conversation) -> tuple[bool, str]:
        from app.services.proactive.repository import (
            conversation_allowed_by_followup_rules,
        )

        return await conversation_allowed_by_followup_rules(self._db, conversation)


class ServiceCandidatePersistenceAdapter:
    """Candidate persistence adapter over the established transactional service."""

    def __init__(self, db) -> None:
        self._db = db

    async def persist(self, command, *, embed_batch, extractor):
        from app.services.candidate_extraction import CandidateExtractionService

        return await CandidateExtractionService.persist(
            self._db,
            embed_batch,
            extractor,
            command.chat_id,
            command.user_text,
            command.bot_output,
            expected_conversation_version=command.expected_conversation_version,
        )


class ServiceProactiveStateAdapter:
    """SQLAlchemy adapter for proactive turn state and history checks."""

    def __init__(self, db) -> None:
        self._db = db

    async def refresh(self, conversation) -> None:
        await self._db.refresh(conversation)

    async def flush(self) -> None:
        await self._db.flush()

    async def commit(self) -> None:
        await self._db.commit()

    async def has_worker_reply_since(self, conversation_id, since) -> bool:
        from sqlalchemy import func, select

        from app.models.conversation import Message, MessageSender

        result = await self._db.execute(
            select(func.count())
            .select_from(Message)
            .where(
                Message.conversation_id == conversation_id,
                Message.sender == MessageSender.WORKER,
                Message.created_at > since,
            )
        )
        return result.scalar() > 0

    async def opt_out_for_silence(self, conversation) -> None:
        conversation.followup_opted_out = True
        await self._db.commit()

    async def stamp_attempt(self, conversation, attempted_at) -> None:
        conversation.last_followup_attempt_at = attempted_at
        await self._db.flush()


__all__ = [
    "ServiceCandidatePersistenceAdapter",
    "ServiceFollowupEligibilityAdapter",
    "ServiceLeadContextAdapter",
    "ServiceProactiveStateAdapter",
]
