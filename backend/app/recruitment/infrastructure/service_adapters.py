"""Adapters over the established recruitment persistence services."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


async def _resolve_lead(db, chat_id: str, contact_id: str | None) -> dict | None:
    """The lead by chat id, else by contact (Messenger rows are contact-keyed)."""
    from app.services.lead.repository import LeadRepository

    repo = LeadRepository(db)
    lead = await repo.by_zalo_id(chat_id) if chat_id else None
    if lead is None and contact_id:
        lead = await repo.by_contact_id(contact_id)
    return lead


async def _persist_profile_name_if_absent(
    db, chat_id: str, name: str, lead: dict | None
) -> bool:
    """Persist an accepted provider profile name into the lead, blank-only.

    Only the OA (``oa:``-prefixed) namespace and already-zalo-keyed rows are
    writable here: the lead upsert is zalo_id-keyed, and a Messenger recipient
    (page-scoped id, NULL ``zalo_id`` lead) upserted as a ``zalo_id`` would
    create a bogus second lead. The COALESCE merge inside the upsert
    guarantees a recruiter-entered or candidate-stated name is never
    overwritten.
    """
    from app.services.lead.normalizers import normalize_lead
    from app.services.lead.repository import LeadRepository

    if not name:
        return False
    zalo_keyed = bool(lead is not None and str(lead.get("zalo_id") or "").strip())
    if not zalo_keyed and not chat_id.startswith("oa:"):
        return False
    patch = normalize_lead({"name": name}, chat_id)
    if patch is None:
        return False
    lead_id = await LeadRepository(db).upsert(patch)
    if lead_id is None:
        return False
    await db.commit()
    return True


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
        profile_name_persisted = False
        if effective_profile_name and not str((lead or {}).get("name") or "").strip():
            # Best-effort: a failed persistence must never break prompt building,
            # which would fail the whole turn. The collection guidance still
            # treats the label as a usable name either way.
            try:
                profile_name_persisted = await _persist_profile_name_if_absent(
                    self._db, chat_id, effective_profile_name, lead
                )
            except Exception:  # noqa: BLE001 — prompt building outranks capture
                logger.debug(
                    "profile-name persistence failed chat=%s", chat_id, exc_info=True
                )
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
        profile_text_lead = (
            collection_lead
            if effective_profile_name and profile_name_persisted
            else lead
        )
        return (
            lead_profile_text(
                profile_text_lead,
                oa_profile_display_name=oa_profile_display_name,
                use_oa_profile_name=effective_profile_name is not None
                and not profile_name_persisted,
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

    async def record_profile_name(
        self,
        chat_id: str,
        name: str,
        *,
        contact_id: str | None = None,
        lead: dict | None = None,
    ) -> bool:
        """Persist a Jev-validated profile display name into a blank lead name.

        Zalo-keyed (OA) rows only — the lead upsert is zalo_id-keyed, so a
        Messenger row (NULL ``zalo_id``) must not be upserted by chat id. The
        COALESCE merge inside the upsert keeps any existing name authoritative.
        """
        if not str(name or "").strip():
            return False
        resolved = lead if lead is not None else await _resolve_lead(self._db, chat_id, contact_id)
        if resolved is not None and str(resolved.get("name") or "").strip():
            return False
        return await _persist_profile_name_if_absent(self._db, chat_id, name.strip(), resolved)


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
