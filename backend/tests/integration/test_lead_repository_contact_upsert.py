"""PostgreSQL coverage for the contact-keyed lead write.

Messenger rows are keyed by ``contact_id`` with a NULL ``zalo_id`` (Alembic
0047), so the zalo_id-keyed upsert violated ``leads_zalo_id_fkey`` and every
Messenger candidate profile was lost. These tests exercise the real statement
against the disposable database: the merge lands on the trigger-created stub
row, leaves ``zalo_id`` NULL, keeps the earliest self-reported value, and
inserts a fresh row when the contact has no lead yet.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import delete, select, update

from app.models.lead import Lead
from app.services.lead.repository import LeadRepository
from tests.integration._conv_factory import make_conversation

pytestmark = pytest.mark.integration


async def _messenger_conversation(db, external_id: str):
    conv = await make_conversation(
        db,
        provider="facebook_messenger",
        account_key="page-1",
        external_id=external_id,
        zalo_chat_id=None,
        zalo_channel="facebook_messenger",
    )
    await db.flush()
    return conv


def _patch(**values):
    patch = {
        "name": None,
        "phone": None,
        "birth_year": None,
        "age": None,
        "living_area": None,
        "address": None,
        "gender": None,
        "region": None,
        "desired_job": None,
        "years_experience": None,
        "expected_salary": None,
        "lead_score": None,
        "notes": None,
    }
    return {**patch, **values}


async def test_merge_lands_on_the_stub_lead_and_keeps_zalo_id_null(integration_session) -> None:
    conv = await _messenger_conversation(integration_session, f"psid-{uuid.uuid4().hex}")
    contact_id = str(conv.contact_id)
    stub = await integration_session.scalar(select(Lead).where(Lead.contact_id == conv.contact_id))
    assert stub is not None, "the 0047 trigger creates the stub lead for the conversation"

    await integration_session.execute(
        update(Lead).where(Lead.id == stub.id).values(name="Mai", version=1)
    )
    await integration_session.flush()

    lead_id = await LeadRepository(integration_session).upsert_by_contact(
        contact_id,
        _patch(
            name="Mai",
            phone="0341234567",
            region="Vĩnh Bảo",
            notes="ở Nam Am, Vĩnh Bảo",
        ),
    )
    await integration_session.flush()

    assert lead_id == stub.id
    saved = await LeadRepository(integration_session).by_contact_id(contact_id)
    assert saved is not None
    assert saved["zalo_id"] is None
    assert saved["name"] == "Mai"
    assert saved["phone"] == "0341234567"
    assert saved["region"] == "Vĩnh Bảo"
    assert saved["notes"] == "ở Nam Am, Vĩnh Bảo"
    assert saved["version"] == 2


async def test_merge_replaces_a_stale_value_but_never_a_blank_one(integration_session) -> None:
    """A later non-blank value wins; a blank one never overwrites what is stored.

    This is what makes a candidate who corrects their phone number land, while a
    turn that happened not to mention the number cannot erase the one already on
    file. ``notes`` is the one accumulating field: the CASE appends only the
    lines that are not already stored.
    """
    conv = await _messenger_conversation(integration_session, f"psid-{uuid.uuid4().hex}")
    contact_id = str(conv.contact_id)
    repo = LeadRepository(integration_session)

    await repo.upsert_by_contact(contact_id, _patch(name="Mai", phone="0341234567"))
    await integration_session.flush()
    await repo.upsert_by_contact(contact_id, _patch(phone="0987654321", notes="Nam Định"))
    await integration_session.flush()

    saved = await repo.by_contact_id(contact_id)
    assert saved is not None
    assert saved["phone"] == "0987654321", "the corrected number replaces the earlier one"
    assert saved["name"] == "Mai", "a blank incoming name must not clear a stored one"
    assert saved["notes"] == "Nam Định"


async def test_merge_does_not_duplicate_an_already_stored_note(integration_session) -> None:
    conv = await _messenger_conversation(integration_session, f"psid-{uuid.uuid4().hex}")
    contact_id = str(conv.contact_id)
    repo = LeadRepository(integration_session)

    await repo.upsert_by_contact(contact_id, _patch(notes="ở Nam Am, Vĩnh Bảo"))
    await integration_session.flush()
    await repo.upsert_by_contact(contact_id, _patch(notes="ở Nam Am, Vĩnh Bảo!"))
    await integration_session.flush()

    saved = await repo.by_contact_id(contact_id)
    assert saved is not None
    assert saved["notes"] == "ở Nam Am, Vĩnh Bảo"


async def test_write_for_a_contact_without_a_lead_inserts_one(integration_session) -> None:
    conv = await _messenger_conversation(integration_session, f"psid-{uuid.uuid4().hex}")
    contact_id = str(conv.contact_id)
    await integration_session.execute(delete(Lead).where(Lead.contact_id == conv.contact_id))
    await integration_session.flush()

    lead_id = await LeadRepository(integration_session).upsert_by_contact(
        contact_id, _patch(name="Hoàng sóng", phone="0566866899", lead_score="warm")
    )
    await integration_session.flush()

    assert lead_id is not None
    saved = await integration_session.scalar(select(Lead).where(Lead.id == lead_id))
    assert saved.contact_id == conv.contact_id
    assert saved.zalo_id is None
    assert saved.name == "Hoàng sóng"
    assert saved.phone == "0566866899"
    assert saved.lead_score == "warm"
    assert saved.version == 1
