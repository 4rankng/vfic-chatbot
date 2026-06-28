"""Phase 3 runtime-wiring tests: persona resolution, master-index assembly, scoped
search_knowledge, list_active_projects, and the idempotent startup seeder."""
import uuid

import pytest
import pytest_asyncio
from sqlalchemy import text

from app.graph.context import active_projects_index, build_system_prompt, resolve_persona
from app.graph.prompts import AGENT_SYSTEM_PROMPT
from app.graph.tools import list_active_projects, search_knowledge
from app.services.seeder import ensure_defaults

pytestmark = pytest.mark.asyncio

VEC = "[" + ",".join(["0.01000000"] * 3072) + "]"


async def emb(_t):
    return [0.01] * 3072


@pytest_asyncio.fixture(autouse=True)
async def _clean_catalog(db_session):
    """Isolate personas + projects per test (the shared DB persists across runs)."""
    await db_session.execute(text("DELETE FROM personas"))
    await db_session.execute(text("DELETE FROM projects"))
    await db_session.commit()
    yield
    await db_session.execute(text("DELETE FROM personas"))
    await db_session.execute(text("DELETE FROM projects"))
    await db_session.commit()


# --------------------------------------------------------------------------- persona
async def test_resolve_persona_falls_back_to_persona_md(db_session):
    # no personas seeded -> persona.md
    assert await resolve_persona(db_session) == AGENT_SYSTEM_PROMPT


async def test_resolve_persona_uses_active_global(db_session, clean_kb):
    await db_session.execute(
        text("INSERT INTO personas(slug,name,body_md,is_active,project_id) "
             "VALUES('p1','P1','NỘI DUNG PERSONA TEST',true,NULL)")
    )
    await db_session.commit()
    assert await resolve_persona(db_session) == "NỘI DUNG PERSONA TEST"


# --------------------------------------------------------------------------- index
async def test_active_projects_index_empty(db_session):
    assert await active_projects_index(db_session) == ""


async def test_active_projects_index_lists_catalog(db_session):
    await db_session.execute(
        text("INSERT INTO projects(slug,name,is_active,summary,index_card) "
             "VALUES ('lg','LG Display',true,'Nhà máy LG',"
             "CAST('{\"key_roles\":[\"operator\",\"thợ điện\"],\"location\":\"Hải Phòng\"}' AS jsonb))")
    )
    await db_session.commit()
    out = await active_projects_index(db_session)
    assert "DANH MỤC" in out
    assert "lg (LG Display)" in out and "Nhà máy LG" in out
    assert "operator" in out and "Hải Phòng" in out
    assert "search_knowledge" in out  # tool guidance present


async def test_build_system_prompt_combines_persona_and_index(db_session):
    await db_session.execute(
        text("INSERT INTO personas(slug,name,body_md,is_active,project_id) "
             "VALUES('p','P','PERSONA BODY',true,NULL)"))
    await db_session.execute(
        text("INSERT INTO projects(slug,name,is_active) VALUES ('lg','LG Display',true)")
    )
    await db_session.commit()
    prompt = await build_system_prompt(db_session)
    assert prompt.startswith("PERSONA BODY")
    assert "DANH MỤC" in prompt and "lg (LG Display)" in prompt


# --------------------------------------------------------------------------- scoped retrieval
async def _seed_doc_chunk(db, doc_id, chunk_content, *, project_id=None):
    await db.execute(
        text("INSERT INTO knowledge_documents(id,file_name,source,status,raw_text,metadata,project_id) "
             "VALUES (CAST(:id AS uuid),'f','google_drive','PUBLISHED','x','{}'::jsonb,CAST(:pid AS uuid))"),
        {"id": doc_id, "pid": str(project_id) if project_id else None},
    )
    await db.execute(
        text("INSERT INTO knowledge_chunks(document_id,chunk_index,content,embedding,metadata,project_id) "
             "VALUES (CAST(:did AS uuid),0,:content,CAST(:e AS vector),'{}'::jsonb,CAST(:pid AS uuid))"),
        {"did": doc_id, "content": chunk_content, "e": VEC, "pid": str(project_id) if project_id else None},
    )


async def test_search_knowledge_scoped_by_project_slug(db_session, clean_kb):
    lg = uuid.uuid4()
    ss = uuid.uuid4()
    await db_session.execute(text("INSERT INTO projects(id,slug,name,is_active) VALUES (CAST(:id AS uuid),'lg','LG',true)"), {"id": str(lg)})
    await db_session.execute(text("INSERT INTO projects(id,slug,name,is_active) VALUES (CAST(:id AS uuid),'samsung','Samsung',true)"), {"id": str(ss)})
    await _seed_doc_chunk(db_session, uuid.uuid4(), "LG Display tuyển operator lương cao", project_id=lg)
    await _seed_doc_chunk(db_session, uuid.uuid4(), "Samsung tuyển thợ điện", project_id=ss)
    await db_session.commit()

    scoped = await search_knowledge(db_session, emb, "tuyển", project_slug="lg")
    assert "LG Display" in scoped
    assert "Samsung" not in scoped

    missing = await search_knowledge(db_session, emb, "tuyển", project_slug="unknown")
    assert "Không tìm thấy" in missing
    assert "LG Display" not in missing
    assert "Samsung" not in missing

    allhits = await search_knowledge(db_session, emb, "tuyển")
    assert "LG Display" in allhits and "Samsung" in allhits


async def test_list_active_projects(db_session):
    await db_session.execute(text("INSERT INTO projects(slug,name,is_active,summary) VALUES ('lg','LG',true,'LG summary')"))
    await db_session.commit()
    out = await list_active_projects(db_session)
    assert "lg (LG)" in out and "LG summary" in out


# --------------------------------------------------------------------------- seeder
async def test_seeder_creates_defaults_idempotently(db_session):
    await ensure_defaults(db_session)
    n_persona = (await db_session.execute(text("SELECT count(*) FROM personas WHERE project_id IS NULL"))).scalar()
    assert n_persona == 1
    assert (await db_session.execute(text("SELECT count(*) FROM projects WHERE slug='vfic'"))).scalar() == 0
    active_body = (await db_session.execute(
        text("SELECT body_md FROM personas WHERE is_active AND project_id IS NULL LIMIT 1")
    )).scalar()
    assert active_body == AGENT_SYSTEM_PROMPT
    # second run is a no-op (still exactly 1 global persona, no synthetic vfic project)
    await ensure_defaults(db_session)
    assert (await db_session.execute(text("SELECT count(*) FROM personas WHERE project_id IS NULL"))).scalar() == 1
    assert (await db_session.execute(text("SELECT count(*) FROM projects WHERE slug='vfic'"))).scalar() == 0
