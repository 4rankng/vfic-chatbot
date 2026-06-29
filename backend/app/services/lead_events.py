"""Realtime seam for lead state changes.

Follows the ConversationEventBus pattern: a single place where lead realtime
events are published so the service layer stays decoupled from transport details.
"""
from __future__ import annotations

from app.schemas.lead import LeadOut
from app.services.realtime import publish_event


def _lead_payload(lead) -> dict:
    """Serialize a lead for the realtime ``lead.updated`` payload."""
    return LeadOut.model_validate(lead).model_dump(mode="json")


class LeadEventBus:
    """Publishes lead realtime events."""

    async def lead_updated(self, lead, *, actor_name: str | None = None) -> None:
        payload = _lead_payload(lead)
        if actor_name:
            payload["actor_name"] = actor_name
        payload["lead_id"] = lead.id
        await publish_event("lead.updated", payload)
