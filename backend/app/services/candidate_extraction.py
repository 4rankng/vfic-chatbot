"""Single candidate extraction pipeline.

One LLM call returns both structured CRM lead fields and memory facts. `leads`
remains the canonical UI/profile store; `memories` remains recall context.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Awaitable, Callable, Literal, cast

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.text import normalize_vietnamese_text
from app.models.conversation import ConversationMode, ConversationStatus
from app.models.lead import Lead
from app.prompts.candidate_extraction import CANDIDATE_EXTRACT_SYSTEM_PROMPT
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

ContactIntent = Literal[
    "candidate",
    "non_candidate",
    "spam",
    "bot_testing",
    "uncertain",
]
_CONTACT_INTENTS: frozenset[str] = frozenset(
    {"candidate", "non_candidate", "spam", "bot_testing", "uncertain"}
)
_HUMAN_REVIEW_INTENTS: frozenset[str] = frozenset(
    {"non_candidate", "spam", "bot_testing"}
)
HUMAN_REVIEW_CONFIDENCE_THRESHOLD = 0.95
_EXPLICIT_HUMAN_REVIEW_EVIDENCE: dict[ContactIntent, tuple[str, ...]] = {
    "non_candidate": (
        "khong phai ung vien",
        "khong phai nguoi tim viec",
        "khong tim viec",
        "khong co nhu cau tim viec",
        "toi khong can tim viec",
        "minh khong can tim viec",
        "toi la nha tuyen dung",
        "minh la nha tuyen dung",
        "toi muon tuyen nguoi",
        "minh muon tuyen nguoi",
        "toi dang tuyen nguoi",
        "minh dang tuyen nguoi",
    ),
    "bot_testing": (
        "toi dang kiem tra bot",
        "minh dang kiem tra bot",
        "toi dang kiem tra chatbot",
        "minh dang kiem tra chatbot",
        "toi dang kiem thu bot",
        "minh dang kiem thu bot",
        "toi dang test bot",
        "minh dang test bot",
        "toi dang test chatbot",
        "minh dang test chatbot",
    ),
    "spam": (
        "toi dang spam",
        "minh dang spam",
        "toi gui spam",
        "minh gui spam",
        "toi muon spam",
        "minh muon spam",
        "toi muon pha he thong",
        "minh muon pha he thong",
    ),
}


def has_explicit_human_review_evidence(user_text: str, intent: ContactIntent) -> bool:
    normalized = normalize_vietnamese_text(user_text or "")
    return any(phrase in normalized for phrase in _EXPLICIT_HUMAN_REVIEW_EVIDENCE.get(intent, ()))


@dataclass(frozen=True)
class CandidateExtraction:
    lead_patch: dict | None
    memory_facts: list[str]
    contact_intent: ContactIntent = "uncertain"
    intent_confidence: float = 0.0

    @property
    def requires_human_review(self) -> bool:
        return (
            self.contact_intent in _HUMAN_REVIEW_INTENTS
            and self.intent_confidence >= HUMAN_REVIEW_CONFIDENCE_THRESHOLD
        )


def _normalize_contact_intent(value, confidence) -> tuple[ContactIntent, float]:
    intent = str(value or "").strip().lower()
    if intent not in _CONTACT_INTENTS:
        return "uncertain", 0.0
    try:
        score = float(confidence)
    except (TypeError, ValueError):
        return "uncertain", 0.0
    if not 0.0 <= score <= 1.0:
        return "uncertain", 0.0
    return cast(ContactIntent, intent), score


def candidate_turn(
    user_text: str,
    bot_output: str,
    *,
    existing_notes: str | None = None,
) -> str:
    saved_notes = (
        existing_notes.strip() if existing_notes and existing_notes.strip() else "(chưa có)"
    )
    return (
        f"Tin nhắn người dùng: {user_text or ''}\n\n"
        f"Phản hồi của bot: {bot_output or ''}\n\n"
        "GHI CHÚ ĐÃ LƯU (chỉ để đối chiếu, không được sao chép, tóm tắt hoặc "
        f"diễn đạt lại):\n{saved_notes}"
    )


def _parse_candidate_json(value) -> dict:
    if isinstance(value, dict):
        return value
    s = str(value if value is not None else "").strip()
    if not s:
        return {}
    s = re.sub(r"^\s*```(?:json)?", "", s, flags=re.IGNORECASE).strip()
    s = re.sub(r"```\s*$", "", s, flags=re.IGNORECASE).strip()
    match = re.search(r"\{[\s\S]*\}", s)
    if not match:
        return {}
    try:
        parsed = json.loads(match.group(0))
    except Exception:  # noqa: BLE001
        return {}
    return parsed if isinstance(parsed, dict) else {}


class CandidateExtractionService:
    @staticmethod
    async def persist_explicit_name(
        db: AsyncSession,
        chat_id: str,
        user_text: str,
    ) -> str | None:
        """Persist an unambiguous self-introduced name on the inbound path.

        This intentionally does not wait for the deferred LLM extraction job.
        The latter still enriches the rest of the candidate profile and can
        overwrite this value only when it has a non-empty extracted name.
        """
        name = extract_self_reported_name(user_text)
        if not name:
            return None
        lead_patch = normalize_lead({"name": name}, chat_id)
        if lead_patch is None:
            return None
        await CandidateExtractionService.upsert_lead(db, lead_patch)
        return name

    @staticmethod
    async def extract(
        extractor: Extractor,
        user_text: str,
        bot_output: str,
        chat_id: str,
        *,
        existing_notes: str | None = None,
    ) -> CandidateExtraction:
        raw = await extractor(
            CANDIDATE_EXTRACT_SYSTEM_PROMPT,
            candidate_turn(user_text, bot_output, existing_notes=existing_notes),
        )
        parsed = _parse_candidate_json(raw)
        lead_patch = normalize_lead(parsed.get("lead_patch"), chat_id)
        if lead_patch and not lead_patch.get("name"):
            lead_patch["name"] = extract_self_reported_name(user_text)
        memory_facts = parse_memory_facts(parsed.get("memory_facts"))
        contact_intent, intent_confidence = _normalize_contact_intent(
            parsed.get("contact_intent"),
            parsed.get("intent_confidence"),
        )
        negative_intent = contact_intent in _HUMAN_REVIEW_INTENTS
        contradictory_payload = negative_intent and (
            any(value for key, value in (lead_patch or {}).items() if key != "zalo_id")
            or bool(memory_facts)
        )
        if negative_intent:
            # Negative intent must never become candidate notes or memory, even below
            # the handoff threshold. Contradictory model output also cannot escalate.
            lead_patch = None
            memory_facts = []
        if contradictory_payload:
            contact_intent = "uncertain"
            intent_confidence = 0.0
        logger.debug(
            "candidate extract: lead=%s memory_facts=%d intent=%s confidence=%.2f "
            "from user text (%d chars)",
            bool(lead_patch),
            len(memory_facts),
            contact_intent,
            intent_confidence,
            len(user_text or ""),
        )
        return CandidateExtraction(
            lead_patch=lead_patch,
            memory_facts=memory_facts,
            contact_intent=contact_intent,
            intent_confidence=intent_confidence,
        )

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
            logger.debug("candidate extraction skipped by greeting_gate: '%s'", user_text[:80])
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
        result = await CandidateExtractionService.extract(
            extractor,
            user_text,
            bot_output,
            chat_id,
            existing_notes=existing_notes,
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
