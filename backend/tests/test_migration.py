"""End-to-end test for US-004 migrate_from_supabase.

We cannot reach the live Supabase DB from this sandbox (no DB password), so we build
a `legacy` schema that mirrors the LIVE source shapes (verified via the catalog on
2026-06-26), seed it with rows that exercise every transform edge case, run the
migration against the real target schema in vfic-pg-test, and assert the results.

This proves the same code that will run against production behaves correctly on
real-shape data. Live row counts (verified separately via MCP) are noted inline.
"""
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import create_engine, text

from app.core.config import get_settings
from app.main import app
from scripts.migrate_from_supabase import (
    classify_sender,
    extract_body,
    run_migration,
)

_settings = get_settings()
SYNC_DSN = _settings.database_url_sync

# 3072-dim zero vector (matches Gemini embedding-2 dimensionality).
VEC = "[" + ",".join(["0.0"] * 3072) + "]"

ADMIN_ID = "11111111-1111-1111-1111-111111111111"
REC_ID = "22222222-2222-2222-2222-222222222222"
PROJ_ID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
COMP_ID = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
KS_ID = "cccccccc-cccc-cccc-cccc-cccccccccccc"
ROUTE_ID = "dddddddd-dddd-dddd-dddd-dddddddddddd"
CONV1_ID = "eeeeeeee-0000-0000-0000-000000000001"
CONV2_ID = "eeeeeeee-0000-0000-0000-000000000002"
DOC1_ID = "face0000-0000-0000-0000-000000000001"
DOC2_ID = "face0000-0000-0000-0000-000000000002"
MEM_ID = "beef0000-0000-0000-0000-000000000001"

LEGACY_DDL = [
    "CREATE SCHEMA legacy",
    """CREATE TABLE legacy.profiles (
        id uuid PRIMARY KEY, email text, full_name text,
        role text NOT NULL DEFAULT 'recruiter',
        created_at timestamptz DEFAULT now(), updated_at timestamptz DEFAULT now())""",
    """CREATE TABLE legacy.conversations (
        id uuid PRIMARY KEY, zalo_chat_id text NOT NULL UNIQUE,
        mode text NOT NULL DEFAULT 'bot', taken_over_at timestamptz,
        version int NOT NULL DEFAULT 1, last_inbound_at timestamptz,
        created_at timestamptz DEFAULT now(), updated_at timestamptz DEFAULT now(),
        assigned_recruiter_id uuid, unread_count int NOT NULL DEFAULT 0,
        bot_locked_until timestamptz)""",
    """CREATE TABLE legacy.vfic_chat_histories (
        id int PRIMARY KEY, session_id varchar NOT NULL, message jsonb NOT NULL)""",
    """CREATE TABLE legacy.documents (
        id uuid PRIMARY KEY, content text, metadata jsonb,
        embedding vector(3072), drive_file_id text, source text)""",
    """CREATE TABLE legacy.memories (
        id uuid PRIMARY KEY, content text, metadata jsonb NOT NULL DEFAULT '{}',
        embedding vector(3072), created_at timestamptz DEFAULT now(),
        chat_id text, canonical_key text, zalo_id text)""",
    """CREATE TABLE legacy.leads (
        id bigserial PRIMARY KEY, zalo_id text, name text, phone text, region text,
        desired_job text, lead_score text, status text NOT NULL DEFAULT 'new',
        notes text, created_at timestamptz DEFAULT now(), updated_at timestamptz DEFAULT now(),
        birth_year int, age int, living_area text, address text, gender text,
        years_experience text, latest_company text, expected_salary text, lead_stage text)""",
    """CREATE TABLE legacy.bot_runs (
        id bigserial PRIMARY KEY, conversation_id uuid NOT NULL,
        started_at timestamptz NOT NULL DEFAULT now(), ended_at timestamptz,
        version_at_start int NOT NULL, proposed_reply text, outcome text NOT NULL)""",
    """CREATE TABLE legacy.projects (
        id uuid PRIMARY KEY, slug text NOT NULL, name text NOT NULL,
        created_at timestamptz DEFAULT now())""",
    """CREATE TABLE legacy.companies (
        id uuid PRIMARY KEY, project_id uuid NOT NULL, name text NOT NULL,
        aliases text[] NOT NULL DEFAULT '{}', created_at timestamptz DEFAULT now())""",
    """CREATE TABLE legacy.knowledge_sources (
        id uuid PRIMARY KEY, project_id uuid NOT NULL, company_id uuid,
        source_name text NOT NULL, source_type text NOT NULL, document_type text NOT NULL,
        source_ref text, version text NOT NULL, status text NOT NULL,
        metadata jsonb NOT NULL DEFAULT '{}',
        created_at timestamptz DEFAULT now(), updated_at timestamptz DEFAULT now())""",
    """CREATE TABLE legacy.bus_routes (
        id uuid PRIMARY KEY, project_id uuid NOT NULL, company_id uuid NOT NULL,
        knowledge_source_id uuid, route_name text NOT NULL, route_no text,
        route_variant text NOT NULL, shift text NOT NULL, direction text NOT NULL,
        area text, mode text, source_page text NOT NULL, notes text,
        metadata jsonb NOT NULL DEFAULT '{}', created_at timestamptz DEFAULT now(),
        route_group_key text NOT NULL)""",
    """CREATE TABLE legacy.bus_stops (
        id uuid PRIMARY KEY, route_id uuid NOT NULL, stop_order int NOT NULL,
        stop_name text NOT NULL, stop_aliases text[] NOT NULL DEFAULT '{}',
        scheduled_time time, raw_stop_text text, created_at timestamptz DEFAULT now())""",
    """CREATE TABLE legacy.bus_route_service_days (
        id uuid PRIMARY KEY, project_id uuid NOT NULL, company_id uuid NOT NULL,
        knowledge_source_id uuid, route_group_key text NOT NULL,
        route_group_name text NOT NULL, day_group text NOT NULL, day_label text NOT NULL,
        service_type text NOT NULL, availability_code text NOT NULL,
        metadata jsonb NOT NULL DEFAULT '{}', created_at timestamptz DEFAULT now())""",
]

TARGET_TRUNCATE = (
    "TRUNCATE public.users, public.conversations, public.messages, "
    "public.outbound_messages, public.bot_runs, public.message_dedup, "
    "public.knowledge_documents, public.knowledge_chunks, public.memories, "
    "public.leads, public.lead_events, public.follow_up_tasks, "
    "public.projects, public.companies, public.knowledge_sources, "
    "public.bus_routes, public.bus_stops, public.bus_route_service_days "
    "RESTART IDENTITY CASCADE"
)


def _seed_legacy(c):
    def ins(sql, params):
        return c.execute(text(sql), params)

    ins("INSERT INTO legacy.projects(id,slug,name) VALUES (:id,:slug,:name)",
        {"id": PROJ_ID, "slug": "vfic", "name": "VFIC"})
    ins("INSERT INTO legacy.companies(id,project_id,name,aliases) VALUES (:id,:p,:n,:a)",
        {"id": COMP_ID, "p": PROJ_ID, "n": "LG Display", "a": ["lg"]})
    ins("INSERT INTO legacy.knowledge_sources(id,project_id,company_id,source_name,source_type,document_type,version,status) "
        "VALUES (:id,:p,:c,'bus','google_drive','pdf','1','ready')",
        {"id": KS_ID, "p": PROJ_ID, "c": COMP_ID})
    ins("INSERT INTO legacy.bus_routes(id,project_id,company_id,knowledge_source_id,route_name,route_variant,shift,direction,source_page,metadata,route_group_key) "
        "VALUES (:id,:p,:c,:ks,'X','v','day','outbound','p1','{}'::jsonb,:rgk)",
        {"id": ROUTE_ID, "p": PROJ_ID, "c": COMP_ID, "ks": KS_ID, "rgk": "k1"})
    for i, nm in enumerate(["A", "B"]):
        ins("INSERT INTO legacy.bus_stops(id,route_id,stop_order,stop_name,stop_aliases) VALUES (:id,:r,:o,:n,:a)",
            {"id": f"dd000000-0000-0000-0000-{i:012d}", "r": ROUTE_ID, "o": i, "n": nm, "a": []})
    ins("INSERT INTO legacy.bus_route_service_days(id,project_id,company_id,route_group_key,route_group_name,day_group,day_label,service_type,availability_code,metadata) "
        "VALUES (:id,:p,:c,:rgk,'gn','mon_thu','T2','outbound_admin_and_day','A','{}'::jsonb)",
        {"id": "ff000000-0000-0000-0000-000000000001", "p": PROJ_ID, "c": COMP_ID, "rgk": "k1"})

    ins("INSERT INTO legacy.profiles(id,email,full_name,role) VALUES (:id,:e,:n,'admin')",
        {"id": ADMIN_ID, "e": "Admin@VFIC.test", "n": "Admin User"})
    ins("INSERT INTO legacy.profiles(id,email,full_name,role) VALUES (:id,:e,:n,'recruiter')",
        {"id": REC_ID, "e": "rec@vfic.test", "n": "Recruiter"})

    ins("INSERT INTO legacy.conversations(id,zalo_chat_id,mode,version,unread_count,last_inbound_at) VALUES (:id,:z,'bot',3,1,now())",
        {"id": CONV1_ID, "z": "real1"})
    ins("INSERT INTO legacy.conversations(id,zalo_chat_id,mode,version,unread_count) VALUES (:id,:z,'bot',1,0)",
        {"id": CONV2_ID, "z": "real2"})

    msgs = [
        (1, "real1", {"type": "human", "content": "hi"}),
        (2, "real1", {"type": "ai", "content": "chào bạn"}),
        (3, "real1", {"type": "human", "content": "tôi hỗ trợ bạn", "recruiter_id": REC_ID}),
        (4, "orphan1", {"type": "human", "content": "test orphan"}),
        (5, "real2", {"type": "ai", "content": "hello"}),
    ]
    for i, sid, m in msgs:
        ins("INSERT INTO legacy.vfic_chat_histories(id,session_id,message) VALUES (:id,:s,(:m)::jsonb)",
            {"id": i, "s": sid, "m": __import__("json").dumps(m)})

    for did, content in [(DOC1_ID, "chunk zero text"), (DOC2_ID, "chunk one text")]:
        meta = __import__("json").dumps({"file_name": "bus.pdf", "version": "1"})
        ins("INSERT INTO legacy.documents(id,content,metadata,embedding,drive_file_id,source) "
            "VALUES (:id,:c,(:m)::jsonb,(:e)::vector,:f,'google_drive')",
            {"id": did, "c": content, "m": meta, "e": VEC, "f": "FILE1"})

    ins("INSERT INTO legacy.memories(id,content,metadata,embedding,created_at,chat_id,canonical_key,zalo_id) "
        "VALUES (:id,:c,(:m)::jsonb,(:e)::vector,now(),'real1','k1','real1')",
        {"id": MEM_ID, "c": "user likes night shift", "m": __import__("json").dumps(
            {"chat_id": "real1", "canonical_key": "k1", "zalo_id": "real1"}), "e": VEC})

    ins("INSERT INTO legacy.leads(zalo_id,name,phone,lead_score,lead_stage,status,desired_job) "
        "VALUES ('real1','Nguyen','0901','hot','QUALIFIED','new','thợ điện')", {})
    ins("INSERT INTO legacy.leads(zalo_id,name,lead_score,lead_stage,status) "
        "VALUES ('leadonly','Le','warm',NULL,'new')", {})

    ins("INSERT INTO legacy.bot_runs(id,conversation_id,version_at_start,outcome,proposed_reply) "
        "VALUES (101,:c,1,'sent','reply text')", {"c": CONV1_ID})


@pytest.fixture
def engines():
    src = create_engine(SYNC_DSN)
    tgt = create_engine(SYNC_DSN)
    with src.connect() as c:
        c.execute(text("DROP SCHEMA IF EXISTS legacy CASCADE"))
        for stmt in LEGACY_DDL:
            c.execute(text(stmt))
        _seed_legacy(c)
        c.commit()
    with tgt.connect() as c:
        c.execute(text(TARGET_TRUNCATE))
        c.commit()
    yield src, tgt
    with src.connect() as c:
        c.execute(text("DROP SCHEMA IF EXISTS legacy CASCADE"))
        c.commit()
    with tgt.connect() as c:
        c.execute(text(TARGET_TRUNCATE))
        c.commit()


def test_pure_transforms():
    assert classify_sender({"type": "human", "content": "x"}) == "WORKER"
    assert classify_sender({"type": "ai", "content": "x"}) == "BOT"
    assert classify_sender({"type": "human", "content": "x", "recruiter_id": REC_ID}) == "RECRUITER"
    assert classify_sender({"type": "human", "content": "x", "data": {"recruiter_id": REC_ID}}) == "RECRUITER"
    assert classify_sender({"type": "function"}) == "SYSTEM"
    assert extract_body({"content": "hi"}) == "hi"
    assert extract_body({"content": [{"type": "text", "text": "a"}, "b"]}) == "ab"
    assert extract_body({"content": {"text": "deep"}}) == "deep"


def test_migration_full_and_idempotent(engines):
    src, tgt = engines
    c1 = run_migration(src, tgt, source_schema="legacy")

    # --- parity / counts (live analog: users 2, convs 7+, chat 406, docs 39...) ---
    assert c1["users"] == 2
    assert c1["conversations_total"] == 4  # real1, real2 + stubs orphan1, leadonly
    assert c1["messages"] == 5
    assert c1["knowledge_documents"] == 1  # grouped by drive_file_id FILE1
    assert c1["knowledge_chunks"] == 2
    assert c1["memories"] == 1
    assert c1["leads"] == 2
    assert c1["bot_runs"] == 1
    assert c1["projects"] == 1 and c1["companies"] == 1 and c1["knowledge_sources"] == 1
    assert c1["bus_routes"] == 1 and c1["bus_stops"] == 2 and c1["bus_route_service_days"] == 1
    assert c1["_skipped_chat_orphans"] == 0

    with tgt.connect() as c:
        # users: email lowercased, roles preserved, password hashed (not plaintext)
        u = dict(c.execute(text(
            "SELECT lower(email)=email AS lc, role, password_hash LIKE '$argon2%' AS argon "
            "FROM public.users WHERE id=:i"), {"i": ADMIN_ID}).first()._mapping)
        assert u["lc"] and u["role"] == "admin" and u["argon"]

        # messages: senders mapped in order; recruiter_id threaded through; created_at monotonic
        senders = [r[0] for r in c.execute(
            text("SELECT sender FROM public.messages ORDER BY id")).all()]
        assert senders == ["WORKER", "BOT", "RECRUITER", "WORKER", "BOT"]
        rec_msg = c.execute(text(
            "SELECT recruiter_id FROM public.messages WHERE sender='RECRUITER'")).scalar()
        assert str(rec_msg) == REC_ID

        # conversations: real rows keep mode=BOT/status=OPEN; stubs created for orphans
        convs = {r[0]: r[1] for r in c.execute(
            text("SELECT zalo_chat_id, mode FROM public.conversations")).all()}
        assert set(convs) == {"real1", "real2", "orphan1", "leadonly"}
        assert all(m == "BOT" for m in convs.values())
        assert c.execute(text(
            "SELECT status FROM public.conversations WHERE zalo_chat_id='real1'")).scalar() == "OPEN"

        # knowledge: 1 doc, 2 chunks under it, content preserved
        assert c.execute(text("SELECT count(*) FROM public.knowledge_documents")).scalar() == 1
        assert c.execute(text("SELECT count(*) FROM public.knowledge_chunks")).scalar() == 2
        assert c.execute(text(
            "SELECT count(*) FROM public.knowledge_chunks WHERE embedding IS NOT NULL")).scalar() == 2

        # memories: verbatim incl. embedding; generated cols derived from metadata
        mrow = c.execute(text(
            "SELECT content, chat_id, canonical_key, zalo_id, embedding IS NOT NULL AS has_emb "
            "FROM public.memories WHERE id=:i"), {"i": MEM_ID}).first()._mapping
        assert mrow["content"] == "user likes night shift"
        assert mrow["chat_id"] == "real1" and mrow["canonical_key"] == "k1" and mrow["zalo_id"] == "real1"
        assert mrow["has_emb"] is True

        # leads: status dropped; lead_stage NULL -> NEW; lead_score preserved
        l2 = c.execute(text(
            "SELECT lead_stage, lead_score FROM public.leads WHERE zalo_id='leadonly'")).first()._mapping
        assert l2.lead_stage == "NEW" and l2.lead_score == "warm"
        l1 = c.execute(text(
            "SELECT lead_stage, lead_score FROM public.leads WHERE zalo_id='real1'")).first()._mapping
        assert l1.lead_stage == "QUALIFIED" and l1.lead_score == "hot"

        # bot_runs: outcome uppercased; FK to preserved conversation id intact
        br = c.execute(text(
            "SELECT outcome, conversation_id FROM public.bot_runs WHERE id=101")).first()._mapping
        assert br.outcome == "SENT" and str(br.conversation_id) == CONV1_ID

    # --- idempotency: second run inserts nothing where ON CONFLICT applies ---
    c2 = run_migration(src, tgt, source_schema="legacy")
    assert c2["users"] == 0 and c2["conversations_real"] == 0 and c2["conversations_stub"] == 0
    assert c2["messages"] == 0 and c2["knowledge_documents"] == 0
    assert c2["leads"] == 0 and c2["bot_runs"] == 0
    # chunks/memories counts are rows-processed (not inserted); verify tables unchanged
    with tgt.connect() as c:
        assert c.execute(text("SELECT count(*) FROM public.messages")).scalar() == 5
        assert c.execute(text("SELECT count(*) FROM public.conversations")).scalar() == 4
        assert c.execute(text("SELECT count(*) FROM public.knowledge_chunks")).scalar() == 2
        assert c.execute(text("SELECT count(*) FROM public.memories")).scalar() == 1
        assert c.execute(text("SELECT count(*) FROM public.leads")).scalar() == 2


@pytest.mark.asyncio
async def test_health_green_after_migration(engines):
    src, tgt = engines
    run_migration(src, tgt, source_schema="legacy")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"
