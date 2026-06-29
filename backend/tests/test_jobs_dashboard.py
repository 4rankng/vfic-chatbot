"""US-009 jobs CRUD + dashboard metrics tests."""
import uuid

import pytest
from sqlalchemy import text

from app.services.dashboard import DashboardService
from app.services.job_service import JobService
from tests.conftest import ADMIN_EMAIL, PASSWORD, RECRUITER_EMAIL

pytestmark = pytest.mark.asyncio

PROJ = "aaaaaaaa-0000-0000-0000-000000000001"
COMP = "bbbbbbbb-0000-0000-0000-000000000001"


async def _seed_company(db_session):
    # `projects.slug` is UNIQUE and the canonical 'vfic' project is also created by the
    # app seeder with an auto-generated id, so a fixed-id seed with ON CONFLICT DO NOTHING
    # can silently no-op on the slug conflict — leaving the companies FK dangling and the
    # test flaking in-suite. Resolve the real project id by slug instead.
    await db_session.execute(text("INSERT INTO projects(id,slug,name) VALUES (:i,'vfic','VFIC') ON CONFLICT (slug) DO NOTHING"), {"i": PROJ})
    proj_id = (await db_session.execute(text("SELECT id FROM projects WHERE slug='vfic'"))).scalar()
    await db_session.execute(text("INSERT INTO companies(id,project_id,name,aliases) VALUES (:i,:p,'LG Display',ARRAY[]::text[]) ON CONFLICT (id) DO UPDATE SET project_id=EXCLUDED.project_id"), {"i": COMP, "p": proj_id})
    await db_session.commit()


async def _admin_tok(client):
    return (await client.post("/api/v1/auth/login", json={"email": ADMIN_EMAIL, "password": PASSWORD})).json()["access_token"]


async def _recruiter_tok(client):
    return (await client.post("/api/v1/auth/login", json={"email": RECRUITER_EMAIL, "password": PASSWORD})).json()["access_token"]


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
    # match_documents indexes usable knowledge chunks; seed one via KnowledgeService.
    from app.services.knowledge_service import KnowledgeService

    async def emb(_):
        return [0.01] * 3072

    svc = KnowledgeService(db_session)
    doc = await svc.upload("jobs.pdf", "LG Display tuyển công nhân lương 15 triệu", drive_file_id="js-1")
    await svc.process(emb, doc)

    rows = await JobService(db_session).search(emb, "LG Display", top_k=5)
    assert any("LG Display" in r["content"] for r in rows)


async def test_dashboard_metrics(client, db_session):
    tok = await _admin_tok(client)
    h = {"Authorization": f"Bearer {tok}"}
    me = (await client.get("/api/v1/auth/me", headers=h)).json()

    # snapshot, then seed: 1 OPEN conversation, 1 hot lead, 1 PENDING follow-up, 1 SENT + 1 SUPPRESSED bot_run.
    # Unique zalo_chat_id per run — the test DB persists across runs and has no
    # per-test cleanup, so a fixed id would trip the zalo_chat_id unique constraint.
    zalo = f"dash-{uuid.uuid4().hex[:8]}"
    before = await DashboardService(db_session).metrics(type("U", (), {"id": uuid.UUID(me["id"]), "role": None})())
    conv_id = uuid.uuid4()
    await db_session.execute(text("INSERT INTO conversations(id,zalo_chat_id,status,mode) VALUES (:i,:z,'OPEN','BOT')"), {"i": conv_id, "z": zalo})
    await db_session.execute(text("INSERT INTO leads(zalo_id,name,lead_score,lead_stage) VALUES (:z,'X','hot','NEW') ON CONFLICT (zalo_id) DO NOTHING"), {"z": zalo})
    lead_id = (await db_session.execute(text("SELECT id FROM leads WHERE zalo_id=:z"), {"z": zalo})).scalar()
    await db_session.execute(text("INSERT INTO follow_up_tasks(lead_id,due_at,status) VALUES (:l,now()+interval '1 day','PENDING')"), {"l": lead_id})
    await db_session.execute(
        text(
            "INSERT INTO bot_runs(conversation_id,version_at_start,outcome,started_at,ended_at) "
            "VALUES "
            "(:c,1,'SENT',now() - interval '3 seconds',now()),"
            "(:c,1,'SUPPRESSED',now() - interval '5 seconds',now())"
        ),
        {"c": conv_id},
    )
    await db_session.commit()

    m = await DashboardService(db_session).metrics(type("U", (), {"id": uuid.UUID(me["id"]), "role": None})())
    assert m.open_conversations >= before.open_conversations + 1
    assert m.hot_leads >= before.hot_leads + 1
    assert m.pending_followups >= before.pending_followups + 1
    assert 0.0 <= m.bot_suppression_rate <= 1.0
    assert m.bot_run_count >= before.bot_run_count + 2
    assert m.bot_sent_count >= before.bot_sent_count + 1
    assert m.bot_suppressed_count >= before.bot_suppressed_count + 1
    assert 0.0 <= m.bot_success_rate <= 100.0
    assert m.avg_bot_response_seconds >= 0.0


async def test_dashboard_metrics_funnel_aggregates(client, db_session):
    """Server-side funnel aggregates replace the old client-side
    useGetList(perPage=1000). Asserts the new fields are scoped, consistent, and
    that stage_breakdown covers every canonical stage and sums to total_leads."""
    tok = await _admin_tok(client)
    h = {"Authorization": f"Bearer {tok}"}

    before = (await client.get("/api/v1/dashboard/metrics", headers=h)).json()

    # Seed 3 unassigned leads across distinct funnel stages (visible to admin
    # and to any recruiter via the assigned_recruiter_id IS NULL scope). Each
    # lead's zalo_id FKs conversations.zalo_chat_id, so seed the conversation
    # first. Unique prefix per run — the test DB persists with no per-test
    # cleanup, so fixed ids would trip the zalo_chat_id unique constraint.
    prefix = uuid.uuid4().hex[:8]
    for suffix, stage in (("q", "QUALIFIED"), ("h", "HIRED"), ("n", "NEW")):
        zalo = f"{prefix}-{suffix}"
        await db_session.execute(
            text(
                "INSERT INTO conversations(id,zalo_chat_id,status,mode) "
                "VALUES (:i,:z,'OPEN','BOT') ON CONFLICT DO NOTHING"
            ),
            {"i": uuid.uuid4(), "z": zalo},
        )
        await db_session.execute(
            text(
                "INSERT INTO leads(zalo_id,name,lead_score,lead_stage) "
                "VALUES (:z,'X','warm',:s) ON CONFLICT (zalo_id) DO NOTHING"
            ),
            {"z": zalo, "s": stage},
        )
    await db_session.commit()

    after = (await client.get("/api/v1/dashboard/metrics", headers=h)).json()

    assert after["total_leads"] == before["total_leads"] + 3
    assert after["qualified_count"] >= before["qualified_count"] + 1
    assert after["hired_count"] >= before["hired_count"] + 1
    # Every canonical stage is present (incl. zero-count) and sums to the total.
    assert [i["value"] for i in after["stage_breakdown"]] == [
        "NEW",
        "ENGAGED",
        "QUALIFIED",
        "APPLIED",
        "HIRED",
        "LOST",
        "UNQUALIFIED",
    ]
    assert sum(i["count"] for i in after["stage_breakdown"]) == after["total_leads"]
    assert after["hired_rate"] == round(after["hired_count"] / after["total_leads"] * 100)
    q_after = next(i for i in after["stage_breakdown"] if i["value"] == "QUALIFIED")["count"]
    q_before = next(i for i in before["stage_breakdown"] if i["value"] == "QUALIFIED")["count"]
    assert q_after >= q_before + 1


async def test_dashboard_knowledge_ingest_health_is_admin_only(client, db_session, clean_kb):
    h_admin = {"Authorization": f"Bearer {await _admin_tok(client)}"}
    h_rec = {"Authorization": f"Bearer {await _recruiter_tok(client)}"}

    await db_session.execute(
        text(
            "INSERT INTO knowledge_documents(file_name,source,status,stage,raw_text,error,updated_at) "
            "VALUES ('bad.txt','upload','FAILED','FAILED','x','MiniMax timeout',now() - interval '20 minutes'), "
            "('slow.txt','upload','PROCESSING','DIGESTING','x',NULL,now() - interval '20 minutes'), "
            "('ok.txt','upload','PUBLISHED','PUBLISHED','x',NULL,now())"
        )
    )
    await db_session.commit()

    admin_body = (await client.get("/api/v1/dashboard/metrics", headers=h_admin)).json()
    rec_body = (await client.get("/api/v1/dashboard/metrics", headers=h_rec)).json()

    health = admin_body["knowledge_ingest"]
    assert health["failed_document_count"] >= 1
    assert health["published_document_count"] >= 1
    assert health["processing_count"] >= 1
    assert health["stuck_count"] >= 1
    assert any(issue["file_name"] == "bad.txt" for issue in health["recent_issues"])
    assert any(row["stage"] == "DIGESTING" for row in health["stage_breakdown"])
    assert rec_body["knowledge_ingest"] is None


async def test_conversations_needs_attention_is_scoped(client, db_session):
    """The bell count endpoint is viewer-scoped: admin sees every human-takeover
    conversation; a recruiter sees only their own + unassigned (NOT another
    staff member's). Decisive proof the scoping isn't accidentally global."""
    h_admin = {"Authorization": f"Bearer {await _admin_tok(client)}"}
    h_rec = {"Authorization": f"Bearer {await _recruiter_tok(client)}"}
    admin_id = (await client.get("/api/v1/auth/me", headers=h_admin)).json()["id"]
    rec_id = (await client.get("/api/v1/auth/me", headers=h_rec)).json()["id"]

    before_admin = (await client.get("/api/v1/conversations/needs-attention", headers=h_admin)).json()["count"]
    before_rec = (await client.get("/api/v1/conversations/needs-attention", headers=h_rec)).json()["count"]

    # Unique zalo ids per run (test DB persists, no per-test cleanup).
    prefix = uuid.uuid4().hex[:8]
    za, zb = f"{prefix}-a", f"{prefix}-b"
    # Conv A: the recruiter's own, in human takeover -> admin + that recruiter.
    await db_session.execute(
        text(
            "INSERT INTO conversations(id,zalo_chat_id,status,mode,assigned_recruiter_id) "
            "VALUES (:i,:z,'OPEN','HUMAN',:rid)"
        ),
        {"i": uuid.uuid4(), "z": za, "rid": rec_id},
    )
    # Conv B: assigned to the admin -> admin sees it, the recruiter does NOT.
    await db_session.execute(
        text(
            "INSERT INTO conversations(id,zalo_chat_id,status,mode,assigned_recruiter_id) "
            "VALUES (:i,:z,'OPEN','HUMAN',:aid)"
        ),
        {"i": uuid.uuid4(), "z": zb, "aid": admin_id},
    )
    await db_session.commit()

    after_admin = (await client.get("/api/v1/conversations/needs-attention", headers=h_admin)).json()["count"]
    after_rec = (await client.get("/api/v1/conversations/needs-attention", headers=h_rec)).json()["count"]

    assert after_admin == before_admin + 2  # admin is global
    assert after_rec == before_rec + 1  # recruiter sees own (A), not the admin's (B)
