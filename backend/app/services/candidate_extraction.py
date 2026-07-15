"""Single candidate extraction pipeline.

One LLM call returns both structured CRM lead fields and memory facts. `leads`
remains the canonical UI/profile store; `memories` remains recall context.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncSession

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


@dataclass(frozen=True)
class CandidateExtraction:
    lead_patch: dict | None
    memory_facts: list[str]


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
        logger.debug(
            "candidate extract: lead=%s memory_facts=%d from user text (%d chars)",
            bool(lead_patch),
            len(memory_facts),
            len(user_text or ""),
        )
        return CandidateExtraction(lead_patch=lead_patch, memory_facts=memory_facts)

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
    ) -> CandidateExtraction:
        if not greeting_gate(user_text):
            logger.debug("candidate extraction skipped by greeting_gate: '%s'", user_text[:80])
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
