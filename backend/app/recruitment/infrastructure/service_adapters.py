"""Adapters over the established recruitment persistence services."""

from __future__ import annotations


async def _resolve_lead(db, chat_id: str, contact_id: str | None) -> dict | None:
    """The lead by chat id, else by contact (Messenger rows are contact-keyed)."""
    from app.services.lead.repository import LeadRepository

    repo = LeadRepository(db)
    lead = await repo.by_zalo_id(chat_id) if chat_id else None
    if lead is None and contact_id:
        lead = await repo.by_contact_id(contact_id)
    return lead


class ServiceLeadContextAdapter:
    """Lead-context query adapter preserving the established prompt behavior."""

    def __init__(self, db) -> None:
        self._db = db

    async def profile_text(self, chat_id: str, contact_id: str | None = None) -> str:
        from app.services.lead import lead_profile_text

        lead = await _resolve_lead(self._db, chat_id, contact_id)
        return lead_profile_text(lead)

    async def context(
        self, chat_id, current_user_text, recent_messages, contact_id=None, lead=None
    ):
        from app.services.conversation import ConversationService
        from app.services.lead import high_confidence_profile_name, lead_profile_text
        from app.services.lead.probing import (
            lead_collection_question,
            oa_profile_name_guidance,
        )

        # ``lead`` is the runner's once-per-turn row; None keeps the adapter's
        # own lookup (ports without the resolve seam, e.g. test doubles).
        lead = lead if lead is not None else await _resolve_lead(self._db, chat_id, contact_id)
        oa_profile_display_name = None
        if chat_id.startswith("oa:"):
            conversation = await ConversationService(self._db).get_by_zalo(chat_id)
            if conversation is not None and conversation.contact is not None:
                oa_profile_display_name = conversation.contact.display_name

        collection_lead = lead
        effective_profile_name = high_confidence_profile_name(oa_profile_display_name)
        if effective_profile_name and not str((lead or {}).get("name") or "").strip():
            collection_lead = dict(lead or {})
            collection_lead["name"] = effective_profile_name
            collection_guidance = lead_collection_question(
                lead=collection_lead,
                current_user_text=current_user_text,
                recent_messages=recent_messages,
            )
        elif oa_profile_display_name and not str((lead or {}).get("name") or "").strip():
            next_question = lead_collection_question(
                lead={**(lead or {}), "name": oa_profile_display_name},
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
                use_oa_profile_name=effective_profile_name is not None,
                personalize=chat_id.startswith("oa:"),
            ),
            collection_guidance,
        )

    def instruction(self, question: str) -> str:
        from app.services.lead.probing import lead_collection_instruction

        return lead_collection_instruction(question=question)


# Canonical address-form values. Anything else (including Vietnamese spellings a
# model may emit) is not usable by address_form() and is left untouched: a
# non-blank value is only ever read, never replaced.
_ADDRESSABLE_GENDERS = frozenset({"male", "female"})


class ServiceLeadGenderAdapter:
    """Lead-record gender memory for the per-turn decision hop."""

    def __init__(self, db) -> None:
        self._db = db

    async def resolve_lead(
        self, chat_id: str, contact_id: str | None = None
    ) -> dict | None:
        """Resolve the turn's lead row once for the runner to hand back in.

        The runner calls this a single time per turn and passes the returned
        row into ``stored_gender`` / ``record_inferred_gender`` (and the
        lead-context adapter), so the by-zalo/by-contact lookup fires once
        instead of once per call site.
        """
        return await _resolve_lead(self._db, chat_id, contact_id)

    async def stored_gender(
        self,
        chat_id: str,
        contact_id: str | None = None,
        *,
        lead: dict | None = None,
    ) -> str:
        lead = lead if lead is not None else await _resolve_lead(self._db, chat_id, contact_id)
        return str((lead or {}).get("gender") or "").strip().lower()

    async def record_inferred_gender(
        self,
        chat_id: str,
        gender: str,
        *,
        contact_id: str | None = None,
        override: bool = False,
        lead: dict | None = None,
    ) -> bool:
        if gender not in _ADDRESSABLE_GENDERS:
            return False
        lead = lead if lead is not None else await _resolve_lead(self._db, chat_id, contact_id)
        if lead is None or lead.get("id") is None:
            return False
        from app.services.lead.repository import LeadRepository

        # Blank-only unless ``override`` is enforced inside the UPDATE itself
        # (``LeadRepository.set_gender_by_id``), so a provider or recruiter write
        # that lands between this call's read and its write is never replaced.
        return await LeadRepository(self._db).set_gender_by_id(
            lead["id"], gender, override=override
        )


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
    "ServiceLeadGenderAdapter",
    "ServiceProactiveStateAdapter",
]
