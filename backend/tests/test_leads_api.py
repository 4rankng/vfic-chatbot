"""US-007 leads CRM API: list/get/patch + assign/stage(->events)/follow-ups."""
import pytest

from app.models.conversation import Conversation
from app.services.lead_service import LeadExtractionService
from tests.conftest import ADMIN_EMAIL, PASSWORD

pytestmark = pytest.mark.asyncio


def _lead(**over) -> dict:
    base = dict.fromkeys(
        ["zalo_id", "name", "phone", "birth_year", "age", "living_area", "address",
         "gender", "region", "desired_job", "years_experience", "latest_company",
         "expected_salary", "lead_score"],
        None,
    )
    base.update(over)
    return base


async def _admin_tok(client) -> str:
    r = await client.post("/api/v1/auth/login", json={"email": ADMIN_EMAIL, "password": PASSWORD})
    assert r.status_code == 200
    return r.json()["access_token"]


async def test_leads_crud_assign_stage_followups(client, db_session):
    conv = Conversation(zalo_chat_id="api-1")
    db_session.add(conv)
    await db_session.commit()
    lead_id = await LeadExtractionService.upsert(db_session, _lead(zalo_id="api-1", name="Dũng", lead_score="warm"))
    assert lead_id is not None

    tok = await _admin_tok(client)
    h = {"Authorization": f"Bearer {tok}"}

    lst = await client.get("/api/v1/leads?per_page=200", headers=h)
    assert lst.status_code == 200
    assert any(ld["id"] == lead_id for ld in lst.json()["data"])

    patched = await client.patch(f"/api/v1/leads/{lead_id}", json={"notes": "gọi lại"}, headers=h)
    assert patched.status_code == 200 and patched.json()["notes"] == "gọi lại"

    staged = await client.post(f"/api/v1/leads/{lead_id}/stage", json={"stage": "QUALIFIED"}, headers=h)
    assert staged.status_code == 200 and staged.json()["lead_stage"] == "QUALIFIED"

    events = await client.get(f"/api/v1/leads/{lead_id}/events", headers=h)
    assert any(e["event_type"] == "stage_change" for e in events.json())

    fu = await client.post(
        f"/api/v1/leads/{lead_id}/follow-ups",
        json={"due_at": "2030-01-01T00:00:00Z", "note": "gọi"},
        headers=h,
    )
    assert fu.status_code == 201
    fus = await client.get(f"/api/v1/leads/{lead_id}/follow-ups", headers=h)
    assert len(fus.json()) == 1

    me = (await client.get("/api/v1/auth/me", headers=h)).json()
    assigned = await client.post(f"/api/v1/leads/{lead_id}/assign", json={"recruiter_id": me["id"]}, headers=h)
    assert assigned.status_code == 200
