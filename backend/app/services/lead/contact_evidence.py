"""Deterministic, durable candidate-phone evidence for recruitment prompts."""

from __future__ import annotations

from datetime import datetime

from app.models.conversation import MessageSender
from app.models.lead import Lead
from app.recruitment.domain.intake import (
    candidate_contact_mobile,
    candidate_mobile,
    candidate_rejected_mobile,
)
from app.services.lead.repository import LeadRepository
from app.services.lead.events import LeadEventBus


async def contact_evidence_context(
    db, lead: dict | None, *, current_user_text: str = "", recent_messages=(),
) -> dict | None:
    """Apply explicit phone evidence to the canonical CRM field before replying."""
    if not lead or lead.get("id") is None:
        return lead
    result = dict(lead)
    accepted = candidate_contact_mobile(current_user_text)
    rejected = candidate_rejected_mobile(current_user_text)
    evidence_phone = accepted or rejected
    repo = LeadRepository(db)
    source = None
    if evidence_phone:
        # Only a durable worker message may author typed evidence. Current
        # turns may combine a burst of inbound messages; find the constituent
        # message that actually carries this candidate-owned number.
        source = next((
            message for message in reversed(recent_messages)
            if getattr(message, "sender", None) == MessageSender.WORKER
            and isinstance(getattr(message, "id", None), int)
            and message.id > 0
            and isinstance(getattr(message, "created_at", None), datetime)
            and str(getattr(message, "body", "") or "").strip()
            and str(message.body).strip() in current_user_text
            and (
                candidate_contact_mobile(message.body) if accepted
                else candidate_rejected_mobile(message.body)
            ) == evidence_phone
        ), None)
        if source is not None:
            result["phone"] = await repo.record_candidate_phone_evidence(
                lead_id=result["id"], phone=evidence_phone, disavowed=not bool(accepted),
                message_id=source.id, occurred_at=source.created_at,
            )
            await db.commit()
            if result["phone"] != lead.get("phone"):
                saved = await db.get(Lead, result["id"])
                if saved is not None:
                    await LeadEventBus().lead_updated(saved)
        elif rejected == candidate_mobile(result.get("phone")):
            # Legacy/test ports without a durable message still get correct
            # guidance this turn; only durable worker evidence may change CRM.
            result["phone"] = None
    return result
