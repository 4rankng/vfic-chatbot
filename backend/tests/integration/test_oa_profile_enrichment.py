"""PostgreSQL coverage for first-contact Zalo OA profile enrichment."""

from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models.contact import Contact
from app.models.lead import Lead
from app.services.conversation import ConversationService
from app.services.profile_enrichment import ProfileEnrichmentService
from app.services.zalo_oa_service import OAUserProfile
from scripts import backfill_oa_profiles as backfill
from tests.integration.conftest import IntegrationDatabase

pytestmark = pytest.mark.integration


async def test_profile_backfill_advisory_lock_allows_only_one_runner(
    integration_database: IntegrationDatabase,
    monkeypatch,
) -> None:
    engine = create_async_engine(integration_database.async_url, pool_pre_ping=True)
    monkeypatch.setattr(backfill, "engine", engine)
    acquired_event = asyncio.Event()
    release_event = asyncio.Event()

    async def hold_first_lock() -> bool:
        async with backfill._exclusive_backfill() as acquired:
            acquired_event.set()
            await release_event.wait()
            return acquired

    try:
        first = asyncio.create_task(hold_first_lock())
        await acquired_event.wait()
        async with backfill._exclusive_backfill() as second_acquired:
            assert second_acquired is False
        release_event.set()
        assert await first is True
        async with backfill._exclusive_backfill() as acquired_after_release:
            assert acquired_after_release is True
    finally:
        release_event.set()
        await engine.dispose()


class _ProfileSender:
    async def get_user_detail(self, user_id: str) -> OAUserProfile | None:
        assert user_id == "first-contact-user"
        return OAUserProfile(
            display_name="Tên từ Zalo",
            avatar_url="https://example.test/avatar.jpg",
        )


class _ConcurrentWriterProfileSender:
    def __init__(self, sessions, contact_id) -> None:
        self._sessions = sessions
        self._contact_id = contact_id

    async def get_user_detail(self, user_id: str) -> OAUserProfile | None:
        assert user_id == "race-user"
        async with self._sessions() as writer:
            await writer.execute(
                update(Contact)
                .where(Contact.id == self._contact_id)
                .values(
                    display_name="Recruiter-confirmed name",
                    avatar_url="https://example.test/recruiter-contact.jpg",
                )
            )
            await writer.execute(
                update(Lead)
                .where(Lead.contact_id == self._contact_id)
                .values(avatar_url="https://example.test/recruiter-lead.jpg")
            )
            await writer.commit()
        return OAUserProfile(
            display_name="Stale provider name",
            avatar_url="https://example.test/stale-provider.jpg",
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

    async def claim(
        _zalo_id: str, *, wait_for_inflight: bool, ignore_done: bool = False
    ):
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


async def test_concurrent_profile_writer_is_not_overwritten(
    integration_database: IntegrationDatabase,
    monkeypatch,
) -> None:
    engine = create_async_engine(integration_database.async_url, pool_pre_ping=True)
    sessions = async_sessionmaker(engine, expire_on_commit=False)

    async def claim(
        _zalo_id: str, *, wait_for_inflight: bool, ignore_done: bool = False
    ):
        return True, "owner"

    async def no_op(*_args, **_kwargs):
        return None

    monkeypatch.setattr("app.services.profile_enrichment._claim_profile_lookup", claim)
    monkeypatch.setattr("app.services.profile_enrichment._mark_profile_lookup_done", no_op)
    monkeypatch.setattr("app.services.profile_enrichment._release_profile_lookup", no_op)
    monkeypatch.setattr("app.services.profile_enrichment.LeadEventBus.lead_updated", no_op)

    try:
        async with sessions() as setup:
            conversation = await ConversationService(setup).ensure(
                "oa:race-user",
                zalo_channel="oa",
            )
            await setup.commit()
            contact_id = conversation.contact_id

        async with sessions() as enrichment_session:
            enriched = await ProfileEnrichmentService(
                enrichment_session,
                _ConcurrentWriterProfileSender(sessions, contact_id),
            ).enrich_oa_user("oa:race-user", user_id="race-user")

        assert enriched is False
        async with sessions() as verify:
            contact = await verify.get(Contact, contact_id)
            lead = await verify.scalar(select(Lead).where(Lead.contact_id == contact_id))
            assert contact is not None
            assert lead is not None
            assert contact.display_name == "Recruiter-confirmed name"
            assert contact.avatar_url == "https://example.test/recruiter-contact.jpg"
            assert lead.avatar_url == "https://example.test/recruiter-lead.jpg"
    finally:
        await engine.dispose()
