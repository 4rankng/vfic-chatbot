"""PostgreSQL coverage for first-contact Zalo OA profile enrichment."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.models.lead import Lead
from app.services.conversation import ConversationService
from app.services.profile_enrichment import ProfileEnrichmentService
from app.services.zalo_oa_service import OAUserProfile

pytestmark = pytest.mark.integration


class _ProfileSender:
    async def get_user_detail(self, user_id: str) -> OAUserProfile | None:
        assert user_id == "first-contact-user"
        return OAUserProfile(
            display_name="Tên từ Zalo",
            avatar_url="https://example.test/avatar.jpg",
        )


async def test_first_oa_conversation_creates_lead_then_enriches_profile(
    integration_session,
    monkeypatch,
) -> None:
    """Alembic's conversation trigger supplies the lead required by enrichment."""
    conversation = await ConversationService(integration_session).ensure(
        "oa:first-contact-user",
        zalo_channel="oa",
    )
    await integration_session.flush()

    lead = await integration_session.scalar(
        select(Lead).where(Lead.zalo_id == "oa:first-contact-user")
    )
    assert lead is not None
    assert lead.name is None

    async def claim(_zalo_id: str, *, wait_for_inflight: bool):
        return True, "owner"

    async def no_op(*_args, **_kwargs):
        return None

    monkeypatch.setattr("app.services.profile_enrichment._claim_profile_lookup", claim)
    monkeypatch.setattr("app.services.profile_enrichment._mark_profile_lookup_done", no_op)
    monkeypatch.setattr("app.services.profile_enrichment._release_profile_lookup", no_op)
    monkeypatch.setattr("app.services.profile_enrichment.LeadEventBus.lead_updated", no_op)

    enriched = await ProfileEnrichmentService(
        integration_session,
        _ProfileSender(),
    ).enrich_oa_user(
        "oa:first-contact-user",
        user_id="first-contact-user",
    )

    assert enriched is True
    await integration_session.refresh(lead)
    await integration_session.refresh(conversation.contact)
    assert lead.name is None
    assert lead.avatar_url == "https://example.test/avatar.jpg"
    assert conversation.contact.display_name == "Tên từ Zalo"
    assert conversation.contact.avatar_url == "https://example.test/avatar.jpg"
