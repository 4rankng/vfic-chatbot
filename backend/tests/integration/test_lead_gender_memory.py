"""PostgreSQL coverage for inferred candidate-gender memory on the lead record.

The per-turn decision hop reads ``leads.gender`` before judging and writes a
confident ``male``/``female`` back, blank-only unless the candidate explicitly
self-refers. These tests exercise the real adapter against the disposable
database, including the migration-0047 trigger that supplies the stub lead
keyed by ``zalo_chat_id``, and the contact-keyed Messenger fallback.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select, update

from app.models.lead import Lead
from app.recruitment.infrastructure.service_adapters import ServiceLeadGenderAdapter
from tests.integration._conv_factory import make_conversation, make_zalo_conversation

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


async def test_messenger_contact_keyed_lead_resolves_by_contact(integration_session) -> None:
    """A Messenger lead has a NULL zalo_id, so only the contact key finds it."""
    conv = await make_conversation(
        integration_session,
        provider="facebook_messenger",
        account_key="page-1",
        external_id="psid-1",
        zalo_chat_id=None,
        zalo_channel="facebook_messenger",
    )
    await integration_session.flush()
    contact_id = str(conv.contact_id)
    adapter = ServiceLeadGenderAdapter(integration_session)

    assert await adapter.stored_gender("", contact_id) == ""
    assert await adapter.record_inferred_gender("", "female", contact_id=contact_id) is True
    assert await adapter.stored_gender("", contact_id) == "female"


async def test_override_replaces_a_stale_value(integration_session) -> None:
    """A bare inference is refused; an explicit self-reference overrides."""
    chat_id = await _blank_lead_chat_id(integration_session, "gender-override-1")
    await integration_session.execute(
        update(Lead).where(Lead.zalo_id == chat_id).values(gender="male")
    )
    await integration_session.flush()
    adapter = ServiceLeadGenderAdapter(integration_session)

    assert await adapter.record_inferred_gender(chat_id, "female") is False
    assert await adapter.stored_gender(chat_id) == "male"

    assert await adapter.record_inferred_gender(chat_id, "female", override=True) is True
    assert await adapter.stored_gender(chat_id) == "female"


async def test_runner_prefetched_lead_row_answers_reads_and_writes(integration_session) -> None:
    """The once-per-turn row from resolve_lead answers stored_gender and the
    inference write without a second by-zalo/by-contact lookup."""
    chat_id = await _blank_lead_chat_id(integration_session, "gender-prefetch-1")
    adapter = ServiceLeadGenderAdapter(integration_session)
    lead = await adapter.resolve_lead(chat_id)

    assert lead is not None and lead.get("id") is not None
    # The prefetched snapshot answers the read and the blank-only write.
    assert await adapter.stored_gender(chat_id, lead=lead) == ""
    assert await adapter.record_inferred_gender(chat_id, "female", lead=lead) is True
    # The write landed on the resolved row's lead id.
    assert await adapter.stored_gender(chat_id) == "female"
    # A non-blank prefetched row keeps refusing a bare inference.
    refreshed = await adapter.resolve_lead(chat_id)
    assert await adapter.record_inferred_gender(chat_id, "male", lead=refreshed) is False


async def test_context_uses_the_prefetched_lead_row(integration_session) -> None:
    """context() with the runner's row produces the same prompt pair as its
    own lookup."""
    from app.recruitment.infrastructure.service_adapters import ServiceLeadContextAdapter

    chat_id = await _blank_lead_chat_id(integration_session, "gender-prefetch-ctx-1")
    lead = await ServiceLeadGenderAdapter(integration_session).resolve_lead(chat_id)
    assert lead is not None

    adapter = ServiceLeadContextAdapter(integration_session)
    prefetched = await adapter.context(chat_id, "tôi muốn tìm việc", [], lead=lead)
    resolved = await adapter.context(chat_id, "tôi muốn tìm việc", [])

    assert prefetched == resolved
