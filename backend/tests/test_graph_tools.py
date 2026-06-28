"""US-006 tool smoke tests: the 3 retrieval tools return seeded data over pgvector
(match_memories / match_documents / search_bus_timetable), with an injected embedder."""
import pytest
from sqlalchemy import text

from app.graph.tools import search_bus_timetable, search_jobs, search_user_memory

pytestmark = pytest.mark.asyncio

# A fixed 3072-dim vector; both the seeded embeddings and the fake embedder use it,
# so cosine similarity is ~1.0 and the seeded rows come back on top.
VEC = "[" + ",".join(["0.01000000"] * 3072) + "]"


async def emb(_text: str):
    return [0.01] * 3072


async def test_search_user_memory_and_jobs(db_session):
    await db_session.execute(
        text(
            "INSERT INTO memories(id, content, metadata, embedding) "
            "VALUES (CAST(:id AS uuid), :content, CAST(:m AS jsonb), CAST(:e AS vector))"
        ),
        {
            "id": "11111111-1111-1111-1111-000000000001",
            "content": "thích làm ca đêm",
            "m": '{"chat_id":"c1","canonical_key":"k","zalo_id":"c1"}',
            "e": VEC,
        },
    )
    await db_session.execute(
        text(
            "INSERT INTO knowledge_documents(id, drive_file_id, file_name, source, status, raw_text, metadata) "
            "VALUES (CAST(:id AS uuid), :df, :fn, :src, :status, :raw, CAST('{}' AS jsonb)) "
            "ON CONFLICT (id) DO NOTHING"
        ),
        {"id": "22222222-2222-2222-2222-000000000001", "df": "f1", "fn": "jobs.pdf",
         "src": "google_drive", "status": "PUBLISHED", "raw": "x"},
    )
    await db_session.execute(
        text(
            "INSERT INTO knowledge_chunks(document_id, chunk_index, content, embedding, metadata) "
            "VALUES (CAST(:did AS uuid), 0, :content, CAST(:e AS vector), CAST('{}' AS jsonb)) "
            "ON CONFLICT (document_id, chunk_index) DO NOTHING"
        ),
        {"did": "22222222-2222-2222-2222-000000000001",
         "content": "LG Display lương 15 triệu/tháng", "e": VEC},
    )
    await db_session.commit()

    mem = await search_user_memory(db_session, emb, "c1", "ca dem")
    assert "ca đêm" in mem
    jobs = await search_jobs(db_session, emb, "LG Display")
    assert "LG Display" in jobs


async def test_search_user_memory_empty(db_session):
    out = await search_user_memory(db_session, emb, "nope", "anything")
    assert "Không" in out


async def test_search_bus_timetable_runs(db_session):
    # no bus data seeded -> tool returns the "not found" string without raising
    out = await search_bus_timetable(db_session, "VFIC", "xe Kiến An ca đêm")
    assert isinstance(out, str)
