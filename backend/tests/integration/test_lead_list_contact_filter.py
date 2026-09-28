"""The CRM conversation panel must be able to find a Messenger lead.

The panel queries ``GET /leads?zalo_id=<conversation.zalo_chat_id>``. A
Messenger conversation has no Zalo chat id, so that request could never reach
its lead and the candidate profile rendered empty no matter what had been
extracted. These tests cover the contact filter the panel now falls back to,
and prove the Zalo filter still resolves the Zalo rows unchanged.
"""

from __future__ import annotations

import uuid

import pytest

from app.models.user import Role, User
from app.services.lead.repository import LeadRepository
from app.services.lead.service import LeadService
from tests.integration._conv_factory import make_conversation

pytestmark = pytest.mark.integration

ADMIN = User(id=uuid.uuid4(), role=Role.admin, email="admin@test", full_name="Admin")


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


async def test_a_messenger_lead_is_reachable_by_contact_id(integration_session) -> None:
    conv = await _messenger_conversation(integration_session, f"psid-{uuid.uuid4().hex}")
    contact_id = str(conv.contact_id)
    await LeadRepository(integration_session).upsert_by_contact(
        contact_id,
        {
            "zalo_id": None,
            "name": "Hoàng sóng",
            "phone": "0566866899",
            "birth_year": None,
            "age": None,
            "living_area": None,
            "address": None,
            "gender": None,
            "region": "Vĩnh Bảo",
            "desired_job": None,
            "years_experience": None,
            "expected_salary": None,
            "lead_score": None,
            "notes": None,
        },
    )
    await integration_session.flush()

    rows, total = await LeadService(integration_session).list(
        viewer=ADMIN,
        page=1,
        per_page=1,
        contact_id=contact_id,
    )

    assert total == 1
    assert [row.name for row in rows] == ["Hoàng sóng"]
    assert rows[0].phone == "0566866899"
    assert rows[0].region == "Vĩnh Bảo"


async def test_the_page_scoped_psid_never_matches_a_lead_by_zalo_id(
    integration_session,
) -> None:
    """The chat id of a contact-keyed provider is not a ``leads.zalo_id``."""
    psid = f"psid-{uuid.uuid4().hex}"
    conv = await _messenger_conversation(integration_session, psid)
    await LeadRepository(integration_session).upsert_by_contact(
        str(conv.contact_id),
        {
            "zalo_id": None,
            "name": "Hoàng sóng",
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
        },
    )
    await integration_session.flush()

    assert conv.zalo_chat_id is None
    rows, total = await LeadService(integration_session).list(
        viewer=ADMIN,
        page=1,
        per_page=1,
        zalo_id=psid,
    )

    assert total == 0
    assert rows == []


async def test_a_zalo_lead_is_still_found_by_its_chat_id(integration_session) -> None:
    chat_id = f"oa-user-{uuid.uuid4().hex}"
    conv = await make_conversation(
        integration_session,
        provider="zalo_oa",
        account_key="oa-1",
        external_id=chat_id,
        zalo_chat_id=chat_id,
        zalo_channel="oa",
    )
    await integration_session.flush()
    await LeadRepository(integration_session).upsert(
        {
            "zalo_id": chat_id,
            "name": "Phạm Hoàng Dũng",
            "phone": "0341234567",
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
    )
    await integration_session.flush()

    rows, total = await LeadService(integration_session).list(
        viewer=ADMIN,
        page=1,
        per_page=1,
        zalo_id=chat_id,
    )

    assert total == 1
    assert rows[0].zalo_id == chat_id
    assert rows[0].contact_id == conv.contact_id
