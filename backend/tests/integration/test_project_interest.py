"""Which dự án a candidate is interested in — recorded, deduped, readable.

Three seams must agree on one idempotent ``lead_events`` row: the outcome
recorder (lead already exists), candidate extraction (the lead is created by
the very job that first sees the signal), and the reader the lead API exposes.
Two signals feed it: the project a campaign link/ad resolved to (Messenger
``ref`` → project slug, resolved at inbound) and the project the conversation
focused on. The focus is channel-neutral; the link resolution is Messenger-first.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from app.conversation_messaging.application.ingress import (
    InboundIdentity,
    InboundTextCommand,
)
from app.conversation_messaging.infrastructure.ingress import (
    SqlAlchemyInboundMessageAdapter,
)
from app.models.company import Project
from app.models.conversation import Conversation
from app.models.lead import LeadEvent
from app.recruitment.domain.candidate_extraction import CandidateExtraction
from app.recruitment.domain.provider import lead_key_for_conversation
from app.services.candidate_extraction import CandidateExtractionService
from app.services.conversation.repository import ConversationRepository
from app.services.conversation.state import ConversationState
from app.services.lead.interest import (
    PROJECT_INTEREST_EVENT,
    SOURCE_CHAT_FOCUS,
    SOURCE_POST_LINK,
    project_interests,
    record_conversation_project_interest,
    record_project_interest,
    resolve_project_by_code,
)
from app.services.lead.normalizers import normalize_lead
from app.services.lead.repository import LeadRepository

pytestmark = pytest.mark.integration

PROVIDER = "zalo_oa"
ACCOUNT = "tingting"


class _RecordingEvents:
    def __init__(self) -> None:
        self.created = 0
        self.updated = 0

    async def message_created(self, *args, **kwargs) -> None:
        self.created += 1

    async def conversation_updated(self, *args, **kwargs) -> None:
        self.updated += 1

    def schedule_realtime(self, *args, **kwargs) -> None:
        return None


async def _conversation(session, external_id: str):
    state = ConversationState(
        session, ConversationRepository(session), _RecordingEvents()
    )
    return await state.ensure_by_identity(
        provider=PROVIDER,
        account_key=ACCOUNT,
        external_id=external_id,
        zalo_chat_id_alias=f"oa:{ACCOUNT}:{external_id}",
        zalo_channel_alias="oa",
    )


async def _project(
    session, *, slug: str, name: str, aliases: list[str] | None = None
) -> Project:
    project = Project(slug=slug, name=name, aliases=aliases or [])
    session.add(project)
    await session.commit()
    await session.refresh(project)
    return project


async def _lead(session, *, chat_id: str) -> int:
    patch = normalize_lead({"name": "Nguyen Van A"}, chat_id)
    assert patch is not None
    lead_id = await LeadRepository(session).upsert(patch)
    assert lead_id is not None
    await session.commit()
    return lead_id


async def _interest_events(session, lead_id: int) -> list[LeadEvent]:
    return list(
        (
            await session.scalars(
                select(LeadEvent)
                .where(
                    LeadEvent.lead_id == lead_id,
                    LeadEvent.event_type == PROJECT_INTEREST_EVENT,
                )
                .order_by(LeadEvent.created_at.asc())
            )
        ).all()
    )


@pytest.mark.asyncio
async def test_interest_is_recorded_once_per_project(integration_session) -> None:
    conv = await _conversation(integration_session, "interest-user-1")
    project = await _project(integration_session, slug="lg-display", name="LG Display")
    lead_id = await _lead(integration_session, chat_id=conv.zalo_chat_id)
    conv.focused_project_id = project.id

    first = await record_conversation_project_interest(integration_session, conv)
    again = await record_conversation_project_interest(integration_session, conv)

    assert first is True
    assert again is False  # every later focused turn stays one row
    events = await _interest_events(integration_session, lead_id)
    assert len(events) == 1
    assert events[0].payload == {
        "project_id": str(project.id),
        "source": "chat_focus",
        "conversation_id": str(conv.id),
    }


@pytest.mark.asyncio
async def test_outcome_seam_records_the_turn_focus(integration_session) -> None:
    conv = await _conversation(integration_session, "interest-user-2")
    project = await _project(integration_session, slug="ssg-bac-ninh", name="SSG Bac Ninh")
    lead_id = await _lead(integration_session, chat_id=conv.zalo_chat_id)

    service = ConversationState(
        integration_session,
        ConversationRepository(integration_session),
        _RecordingEvents(),
    )
    base = dict(
        version_at_start=conv.version,
        reply="Luong tai duan khoang 12 trieu.",
        started_at=datetime.now(timezone.utc),
        sent=True,
    )

    # No project signal on the conversation → nothing to record, whatever the
    # turn's timings say (the recorder is signal-driven, not timing-driven).
    conv.focused_project_id = None
    await service.record_bot_outcome(conv, **base, stage_timings={"lane": "general"})
    assert await _interest_events(integration_session, lead_id) == []

    # Signal present → recorded by the next outcome.
    conv.focused_project_id = project.id
    await service.record_bot_outcome(conv, **base, stage_timings={"lane": "general"})
    events = await _interest_events(integration_session, lead_id)
    assert [event.payload["project_id"] for event in events] == [str(project.id)]
    assert [event.payload["source"] for event in events] == ["chat_focus"]


@pytest.mark.asyncio
async def test_extraction_seam_creates_the_lead_and_the_interest(
    integration_session, monkeypatch
) -> None:
    """The extraction backstop attaches the signals it finds on the conversation.

    A turn whose outcome never ran (crash, reconcile) still ends here once the
    job executes, and the zalo-keyed lead the job upserts is the row the
    interest lands on.
    """
    conv = await _conversation(integration_session, "interest-user-3")
    project = await _project(integration_session, slug="vus-1", name="VUS")
    conv.focused_project_id = project.id
    await integration_session.commit()

    chat_id = conv.zalo_chat_id
    patch = normalize_lead({"name": "Tran Thi B"}, chat_id)
    assert patch is not None
    monkeypatch.setattr(
        CandidateExtractionService,
        "extract",
        AsyncMock(return_value=CandidateExtraction(lead_patch=patch, memory_facts=[])),
    )

    result = await CandidateExtractionService.persist(
        integration_session,
        None,  # embedder: unused, memory_facts is empty
        None,  # extractor: extract() is stubbed
        chat_id,
        "Minh muon tim hieu viec lam tai du an VUS va muc luong o day",
        "Du an VUS dang tuyen dung",
        conversation_id=str(conv.id),
    )
    assert result.lead_patch is not None

    key = lead_key_for_conversation(conv)
    assert key.zalo_id is not None
    lead = await LeadRepository(integration_session).by_zalo_id(key.zalo_id)
    assert lead is not None
    events = await _interest_events(integration_session, int(lead["id"]))
    assert [event.payload["project_id"] for event in events] == [str(project.id)]


@pytest.mark.asyncio
async def test_reader_resolves_current_project_names_in_order(
    integration_session,
) -> None:
    conv = await _conversation(integration_session, "interest-user-4")
    first = await _project(integration_session, slug="lg-display", name="LG Display")
    second = await _project(integration_session, slug="ssg-bac-ninh", name="SSG Bac Ninh")
    lead_id = await _lead(integration_session, chat_id=conv.zalo_chat_id)

    assert await record_project_interest(
        integration_session,
        lead_id=lead_id,
        project_id=first.id,
        source=SOURCE_CHAT_FOCUS,
        conversation_id=conv.id,
    )
    # A deleted project must drop out of the list instead of breaking it.
    ghost_id = uuid.uuid4()
    await record_project_interest(
        integration_session,
        lead_id=lead_id,
        project_id=ghost_id,
        source=SOURCE_CHAT_FOCUS,
        conversation_id=conv.id,
    )
    await record_project_interest(
        integration_session,
        lead_id=lead_id,
        project_id=second.id,
        source=SOURCE_CHAT_FOCUS,
        conversation_id=conv.id,
    )
    await integration_session.commit()

    interests = await project_interests(integration_session, lead_id)

    assert [(row["project_slug"], row["project_name"]) for row in interests] == [
        ("lg-display", "LG Display"),
        ("ssg-bac-ninh", "SSG Bac Ninh"),
    ]
    assert all(row["source"] == SOURCE_CHAT_FOCUS for row in interests)
    assert all(row["project_id"] != ghost_id for row in interests)


@pytest.mark.asyncio
async def test_campaign_code_resolves_to_a_project(integration_session) -> None:
    lg = await _project(integration_session, slug="lg-display", name="LG Display")
    vus = await _project(
        integration_session, slug="vus-1", name="VUS", aliases=["VUS10"]
    )

    assert await resolve_project_by_code(integration_session, "LG-Display") == str(lg.id)
    assert await resolve_project_by_code(integration_session, "  vus10 ") == str(vus.id)
    assert await resolve_project_by_code(integration_session, "khong-ton-tai") is None
    assert await resolve_project_by_code(integration_session, "") is None
    assert await resolve_project_by_code(integration_session, None) is None


@pytest.mark.asyncio
async def test_messenger_inbound_resolves_the_ad_ref_to_a_project(
    integration_session,
) -> None:
    """A candidate who clicks an ad is filed under its dự án before typing.

    The ``ref`` of the Messenger referral resolves to a project at inbound, the
    resolved id lands in the conversation's attribution (first touch wins), and
    the interest event follows as soon as the lead row exists — which for a new
    candidate is the extraction job.
    """
    project = await _project(integration_session, slug="lg-display", name="LG Display")
    adapter = SqlAlchemyInboundMessageAdapter(integration_session)
    command = InboundTextCommand(
        identity=InboundIdentity(
            provider="facebook_messenger",
            account_key="page-1",
            external_id="psid-campaign",
        ),
        external_message_id="mid-campaign-1",
        text="minh quan tam viec lam tai LG",
        attribution={
            "kind": "referral",
            "post_code": "LG-Display",  # stored as sent; matched case-insensitively
            "ad_id": "1234567890",
            "referral_source": "ADS",
        },
    )

    persisted = await adapter.persist(command)
    assert persisted is not None

    conv = (
        await integration_session.scalars(
            select(Conversation).where(
                Conversation.id == uuid.UUID(persisted.conversation_id)
            )
        )
    ).one()
    assert conv.attribution["post_code"] == "LG-Display"
    assert conv.attribution["ad_id"] == "1234567890"
    assert conv.attribution["project_id"] == str(project.id)

    # The conversation trigger (Alembic 0047) creates a lead row with the
    # conversation, so the campaign interest is ready for the next seam —
    # invoked here directly (production reaches it via the turn outcome).
    assert await record_conversation_project_interest(integration_session, conv) is True
    lead = await LeadRepository(integration_session).by_contact_id(str(conv.contact_id))
    assert lead is not None
    events = await _interest_events(integration_session, int(lead["id"]))
    assert [event.payload["source"] for event in events] == [SOURCE_POST_LINK]
    assert events[0].payload["project_id"] == str(project.id)
    # Idempotent: the following seam adds no second row.
    assert await record_conversation_project_interest(integration_session, conv) is False
