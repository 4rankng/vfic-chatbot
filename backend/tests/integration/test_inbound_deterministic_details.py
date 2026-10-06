"""Deterministic lead details land on the inbound path (real PostgreSQL).

The deferred LLM job used to be the only writer for age/salary (and the only
name writer on Messenger), so a queue hiccup, a model failure, or a review gate
meant the candidate's details never reached the CRM. These pins prove the
closed-shape fields are written while the message is being persisted — before
any queue, model, or gate is involved.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.conversation_messaging.application.ingress import (
    InboundIdentity,
    InboundTextCommand,
)
from app.conversation_messaging.infrastructure.ingress import (
    SqlAlchemyInboundMessageAdapter,
)
from app.models.conversation import Conversation
from app.services.lead.repository import LeadRepository

pytestmark = pytest.mark.integration


async def _lead_for_conversation(session, conversation_id: str) -> dict:
    conversation = (
        await session.scalars(
            select(Conversation).where(Conversation.id == uuid.UUID(conversation_id))
        )
    ).one()
    lead = await LeadRepository(session).by_contact_id(str(conversation.contact_id))
    assert lead is not None
    return lead


@pytest.mark.asyncio
async def test_messenger_inbound_writes_name_age_and_salary_before_any_queue(
    integration_session,
) -> None:
    adapter = SqlAlchemyInboundMessageAdapter(integration_session)

    persisted = await adapter.persist(
        InboundTextCommand(
            identity=InboundIdentity(
                provider="facebook_messenger",
                account_key="page-1",
                external_id="psid-details-1",
            ),
            external_message_id="mid-details-1",
            text="mình tên Nguyễn Văn An, 25 tuổi, lương mong muốn 12 triệu",
        )
    )

    assert persisted is not None
    lead = await _lead_for_conversation(integration_session, persisted.conversation_id)
    assert lead["name"] == "Nguyễn Văn An"
    assert lead["age"] == 25
    assert lead["expected_salary"] == "12 triệu"


@pytest.mark.asyncio
async def test_details_without_a_name_still_fill_the_numeric_fields(
    integration_session,
) -> None:
    adapter = SqlAlchemyInboundMessageAdapter(integration_session)

    persisted = await adapter.persist(
        InboundTextCommand(
            identity=InboundIdentity(
                provider="facebook_messenger",
                account_key="page-1",
                external_id="psid-details-2",
            ),
            external_message_id="mid-details-2",
            text="mình 25 tuổi, lương mong muốn 12-14 triệu",
        )
    )

    assert persisted is not None
    lead = await _lead_for_conversation(integration_session, persisted.conversation_id)
    assert lead["age"] == 25
    assert lead["expected_salary"] == "12-14 triệu"
    assert lead["name"] is None  # never guessed, only captured


@pytest.mark.asyncio
async def test_a_message_without_any_detail_writes_nothing(
    integration_session,
) -> None:
    adapter = SqlAlchemyInboundMessageAdapter(integration_session)

    persisted = await adapter.persist(
        InboundTextCommand(
            identity=InboundIdentity(
                provider="facebook_messenger",
                account_key="page-1",
                external_id="psid-details-3",
            ),
            external_message_id="mid-details-3",
            text="công ty có xe đưa đón không?",
        )
    )

    assert persisted is not None
    lead = await _lead_for_conversation(integration_session, persisted.conversation_id)
    assert lead["name"] is None
    assert lead["age"] is None
    assert lead["expected_salary"] is None


@pytest.mark.asyncio
async def test_zalo_keyed_write_merges_into_the_stub_lead(
    integration_session,
) -> None:
    """The same deterministic pass on a Zalo conversation.

    The conversation trigger already created the lead (both ``zalo_id`` and
    ``contact_id`` set, Alembic 0047), so the details must merge into THAT row
    — not insert a second one beside it.
    """
    from app.models.lead import Lead
    from app.services.candidate_extraction import CandidateExtractionService
    from app.services.conversation.repository import ConversationRepository
    from app.services.conversation.state import ConversationState

    state = ConversationState(
        integration_session, ConversationRepository(integration_session), _NoEvents()
    )
    conversation = await state.ensure_by_identity(
        provider="zalo_oa",
        account_key="tingting",
        external_id="details-user-1",
        zalo_chat_id_alias="oa:tingting:details-user-1",
        zalo_channel_alias="oa",
    )
    await integration_session.commit()

    captured = await CandidateExtractionService.persist_explicit_details(
        integration_session,
        str(conversation.zalo_chat_id),
        "mình tên Trần Thị Bình, sn 1998, lương 10 triệu",
        conversation=conversation,
    )

    assert captured == "Trần Thị Bình"
    rows = list(
        (
            await integration_session.scalars(
                select(Lead).where(Lead.contact_id == conversation.contact_id)
            )
        ).all()
    )
    assert len(rows) == 1  # merged into the stub, never a second row
    assert rows[0].name == "Trần Thị Bình"
    assert rows[0].birth_year == 1998
    assert rows[0].age is not None  # derived from the year by normalize_lead
    assert rows[0].expected_salary == "10 triệu"


class _NoEvents:
    async def message_created(self, *args, **kwargs) -> None:
        return None

    async def conversation_updated(self, *args, **kwargs) -> None:
        return None

    def schedule_realtime(self, *args, **kwargs) -> None:
        return None
