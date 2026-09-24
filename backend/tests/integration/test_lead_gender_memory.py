"""PostgreSQL coverage for inferred candidate-gender memory on the lead record.

The per-turn decision hop reads ``leads.gender`` before judging and writes a
confident ``male``/``female`` back only when the column is blank. These tests
exercise the real adapter against the disposable database, including the
migration-0047 trigger that supplies the stub lead keyed by ``zalo_chat_id``.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select, update

from app.models.lead import Lead
from app.recruitment.infrastructure.service_adapters import ServiceLeadGenderAdapter
from tests.integration._conv_factory import make_zalo_conversation

pytestmark = pytest.mark.integration


async def _blank_lead_chat_id(db, chat_id: str) -> str:
    """Create the conversation (and its trigger-created stub lead) for ``chat_id``."""
    await make_zalo_conversation(db, zalo_chat_id=chat_id)
    await db.flush()
    return chat_id


async def test_blank_lead_records_then_refuses_overwrite(integration_session) -> None:
    chat_id = await _blank_lead_chat_id(integration_session, "gender-blank-1")
    adapter = ServiceLeadGenderAdapter(integration_session)

    assert await adapter.stored_gender(chat_id) == ""
    assert await adapter.record_inferred_gender(chat_id, "female") is True
    assert await adapter.stored_gender(chat_id) == "female"

    # Second inference cannot overwrite the now non-blank value.
    assert await adapter.record_inferred_gender(chat_id, "male") is False
    assert await adapter.stored_gender(chat_id) == "female"


async def test_non_blank_value_is_never_replaced(integration_session) -> None:
    chat_id = await _blank_lead_chat_id(integration_session, "gender-preset-1")
    await integration_session.execute(
        update(Lead).where(Lead.zalo_id == chat_id).values(gender="nam")
    )
    await integration_session.flush()

    adapter = ServiceLeadGenderAdapter(integration_session)
    assert await adapter.stored_gender(chat_id) == "nam"
    assert await adapter.record_inferred_gender(chat_id, "male") is False
    assert await adapter.stored_gender(chat_id) == "nam"


async def test_unknown_gender_writes_nothing(integration_session) -> None:
    chat_id = await _blank_lead_chat_id(integration_session, "gender-unknown-1")
    adapter = ServiceLeadGenderAdapter(integration_session)

    assert await adapter.record_inferred_gender(chat_id, "unknown") is False
    assert await adapter.stored_gender(chat_id) == ""


async def test_missing_chat_id_is_a_noop(integration_session) -> None:
    adapter = ServiceLeadGenderAdapter(integration_session)

    assert await adapter.stored_gender("missing-chat-id") == ""
    assert await adapter.record_inferred_gender("missing-chat-id", "male") is False


async def test_stored_gender_reads_committed_row(integration_session) -> None:
    """A value committed by another writer is what the next turn reads."""
    chat_id = await _blank_lead_chat_id(integration_session, "gender-committed-1")
    await integration_session.execute(
        update(Lead).where(Lead.zalo_id == chat_id).values(gender="female")
    )
    await integration_session.commit()

    assert await ServiceLeadGenderAdapter(integration_session).stored_gender(chat_id) == "female"
    lead = await integration_session.scalar(select(Lead).where(Lead.zalo_id == chat_id))
    assert lead.gender == "female"
