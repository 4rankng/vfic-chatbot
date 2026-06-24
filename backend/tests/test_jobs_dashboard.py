"""US-009 jobs CRUD + dashboard metrics tests."""
import uuid

import pytest
from sqlalchemy import text

from app.services.dashboard_service import DashboardService
from app.services.job_service import JobService
from tests.conftest import ADMIN_EMAIL, PASSWORD

pytestmark = pytest.mark.asyncio

PROJ = "aaaaaaaa-0000-0000-0000-000000000001"
COMP = "bbbbbbbb-0000-0000-0000-000000000001"


async def _seed_company(db_session):
    await db_session.execute(text("INSERT INTO projects(id,slug,name) VALUES (:i,'vfic','VFIC') ON CONFLICT DO NOTHING"), {"i": PROJ})
    await db_session.execute(text("INSERT INTO companies(id,project_id,name,aliases) VALUES (:i,:p,'LG Display',ARRAY[]::text[]) ON CONFLICT DO NOTHING"), {"i": COMP, "p": PROJ})
    await db_session.commit()


async def _admin_tok(client):
    return (await client.post("/api/v1/auth/login", json={"email": ADMIN_EMAIL, "password": PASSWORD})).json()["access_token"]


async def test_jobs_crud(client, db_session):
    await _seed_company(db_session)
    tok = await _admin_tok(client)
    h = {"Authorization": f"Bearer {tok}"}

    created = await client.post(
        "/api/v1/jobs",
        json={"title": "Công nhân LG Display", "company_id": COMP, "province": "Hải Phòng", "salary_min": 15000000, "vacancy_count": 20},
        headers=h,
    )
    assert created.status_code == 201, created.text
    jid = created.json()["id"]

    lst = await client.get("/api/v1/jobs", headers=h)
    assert lst.status_code == 200 and any(j["id"] == jid for j in lst.json()["data"])

    patched = await client.patch(f"/api/v1/jobs/{jid}", json={"vacancy_count": 5}, headers=h)
    assert patched.json()["vacancy_count"] == 5

    archived = await client.post(f"/api/v1/jobs/{jid}/archive", headers=h)
    assert archived.json()["status"] == "ARCHIVED"


async def test_job_semantic_search_runs(db_session, clean_kb):
    # match_documents needs APPROVED knowledge chunks; seed one via KnowledgeService
    from app.services.knowledge_service import KnowledgeService

    async def emb(_):
        return [0.01] * 3072

    svc = KnowledgeService(db_session)
    doc = await svc.upload("jobs.pdf", "LG Display tuyển công nhân lương 15 triệu", drive_file_id="js-1")
    from types import SimpleNamespace

    admin_id = (await db_session.execute(text("SELECT id FROM users WHERE email=:e"), {"e": ADMIN_EMAIL})).scalar()
    await svc.process(emb, doc)
    await svc.approve(doc, actor=SimpleNamespace(id=admin_id))

    rows = await JobService(db_session).search(emb, "LG Display", top_k=5)
    assert any("LG Display" in r["content"] for r in rows)


async def test_dashboard_metrics(client, db_session):
    tok = await _admin_tok(client)
    h = {"Authorization": f"Bearer {tok}"}
    me = (await client.get("/api/v1/auth/me", headers=h)).json()

    # snapshot, then seed: 1 OPEN conversation, 1 hot lead, 1 PENDING follow-up, 1 SENT + 1 SUPPRESSED bot_run
    before = await DashboardService(db_session).metrics(type("U", (), {"id": uuid.UUID(me["id"]), "role": None})())
    conv_id = uuid.uuid4()
    await db_session.execute(text("INSERT INTO conversations(id,zalo_chat_id,status,mode) VALUES (:i,'dash-1','OPEN','BOT')"), {"i": conv_id})
    await db_session.execute(text("INSERT INTO leads(zalo_id,name,lead_score,lead_stage) VALUES ('dash-1','X','hot','NEW') ON CONFLICT (zalo_id) DO NOTHING"))
    lead_id = (await db_session.execute(text("SELECT id FROM leads WHERE zalo_id='dash-1'"))).scalar()
    await db_session.execute(text("INSERT INTO follow_up_tasks(lead_id,due_at,status) VALUES (:l,now()+interval '1 day','PENDING')"), {"l": lead_id})
    await db_session.execute(text("INSERT INTO bot_runs(conversation_id,version_at_start,outcome) VALUES (:c,1,'SENT'),(:c,1,'SUPPRESSED')"), {"c": conv_id})
    await db_session.commit()

    m = await DashboardService(db_session).metrics(type("U", (), {"id": uuid.UUID(me["id"]), "role": None})())
    assert m.open_conversations >= before.open_conversations + 1
    assert m.hot_leads >= before.hot_leads + 1
    assert m.pending_followups >= before.pending_followups + 1
    assert 0.0 <= m.bot_suppression_rate <= 1.0
