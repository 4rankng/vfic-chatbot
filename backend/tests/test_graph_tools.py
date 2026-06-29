"""US-006 tool smoke tests: the 3 retrieval tools return seeded data over pgvector
(match_memories / match_documents / search_bus_timetable), with an injected embedder."""
import pytest
from sqlalchemy import text

from app.graph.tools import search_bus_timetable, search_jobs, search_knowledge, search_user_memory
from app.services.memory_service import greeting_gate

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


async def test_search_knowledge_does_not_truncate_answer_bearing_chunk(db_session):
    long_content = (
        "Thông tin đầu chunk. "
        + ("phần đệm " * 45)
        + "CHI_TIET_SAU_KY_TU_300: Cty TNHH Hào Quang 06:35, BV An Lão 2 06:50."
    )
    assert long_content.index("CHI_TIET_SAU_KY_TU_300") > 300
    await db_session.execute(
        text(
            "INSERT INTO knowledge_documents(id, drive_file_id, file_name, source, status, raw_text, metadata) "
            "VALUES (CAST(:id AS uuid), :df, :fn, :src, :status, :raw, CAST('{}' AS jsonb)) "
            "ON CONFLICT (id) DO NOTHING"
        ),
        {
            "id": "22222222-2222-2222-2222-000000000002",
            "df": "f2",
            "fn": "long.md",
            "src": "upload",
            "status": "PUBLISHED",
            "raw": long_content,
        },
    )
    await db_session.execute(
        text(
            "INSERT INTO knowledge_chunks(document_id, chunk_index, content, embedding, metadata) "
            "VALUES (CAST(:did AS uuid), 0, :content, CAST(:e AS vector), CAST(:m AS jsonb)) "
            "ON CONFLICT (document_id, chunk_index) DO UPDATE SET content = EXCLUDED.content, metadata = EXCLUDED.metadata"
        ),
        {
            "did": "22222222-2222-2222-2222-000000000002",
            "content": long_content,
            "e": VEC,
            "m": '{"citation":{"label":"Long KB","source_anchor":"Full chunk"}}',
        },
    )
    await db_session.commit()

    out = await search_knowledge(db_session, emb, "Hào Quang")
    assert "CHI_TIET_SAU_KY_TU_300" in out
    assert "BV An Lão 2 06:50" in out
    assert "Nguồn: Long KB (Full chunk)" in out


async def test_search_bus_timetable_runs(db_session):
    # no bus data seeded -> tool returns the "not found" string without raising
    out = await search_bus_timetable(db_session, "VFIC", "xe Kiến An ca đêm")
    assert isinstance(out, str)


# ---------------------------------------------------------------------------
# F1: Similarity floor — near-zero-similarity chunks must be excluded
async def test_search_knowledge_excludes_low_similarity_chunk(db_session):
    """A chunk with anti-parallel embedding must not appear.

    pgvector treats all-zero vectors as NaN-similarity, so we use an
    anti-parallel vector instead (cosine distance=2, similarity=1-2=-1.0).
    """
    good_vec = "[" + ",".join(["0.01000000"] * 3072) + "]"
    # Anti-parallel: cosine similarity = -1.0 → similarity = 1 - (1-(-1)) = -1.0
    bad_vec = "[" + ",".join(["-0.01000000"] * 3072) + "]"

    await db_session.execute(
        text(
            "INSERT INTO knowledge_documents(id, drive_file_id, file_name, source, status, raw_text, metadata) "
            "VALUES (CAST(:id AS uuid), :df, :fn, :src, :status, :raw, CAST('{}' AS jsonb)) "
            "ON CONFLICT (id) DO NOTHING"
        ),
        {"id": "33333333-3333-3333-3333-000000000001", "df": "f_sim", "fn": "sim_test.md",
         "src": "upload", "status": "PUBLISHED", "raw": "x"},
    )
    # High-similarity chunk (embedder returns 0.01 vectors, so sim ~1.0)
    await db_session.execute(
        text(
            "INSERT INTO knowledge_chunks(document_id, chunk_index, content, embedding, metadata) "
            "VALUES (CAST(:did AS uuid), 0, :content, CAST(:e AS vector), CAST('{}' AS jsonb)) "
            "ON CONFLICT (document_id, chunk_index) DO NOTHING"
        ),
        {"did": "33333333-3333-3333-3333-000000000001",
         "content": "RELEVANT_CHUNK_DATA", "e": good_vec},
    )
    # Low-similarity chunk (anti-parallel vector → sim = -1.0, below 0.30 floor)
    # Uses DO UPDATE to replace stale data from prior test runs.
    await db_session.execute(
        text(
            "INSERT INTO knowledge_chunks(document_id, chunk_index, content, embedding, metadata) "
            "VALUES (CAST(:did AS uuid), 1, :content, CAST(:e AS vector), CAST('{}' AS jsonb)) "
            "ON CONFLICT (document_id, chunk_index) DO UPDATE SET embedding = EXCLUDED.embedding, content = EXCLUDED.content"
        ),
        {"did": "33333333-3333-3333-3333-000000000001",
         "content": "NOISE_CHUNK_SHOULD_BE_EXCLUDED", "e": bad_vec},
    )
    await db_session.commit()

    out = await search_knowledge(db_session, emb, "RELEVANT_CHUNK_DATA")
    assert "RELEVANT_CHUNK_DATA" in out
    assert "NOISE_CHUNK_SHOULD_BE_EXCLUDED" not in out


# ---------------------------------------------------------------------------
# FAQ-first pre-pass: FAQ chunks above floor are prepended
async def test_search_knowledge_faq_prepass(db_session):
    """FAQ chunks (category='faq') above the FAQ floor are prepended as a canonical block."""
    good_vec = "[" + ",".join(["0.01000000"] * 3072) + "]"
    faq_doc_id = "44444444-4444-4444-4444-000000000001"

    await db_session.execute(
        text(
            "INSERT INTO knowledge_documents(id, drive_file_id, file_name, source, status, raw_text, metadata) "
            "VALUES (CAST(:id AS uuid), :df, :fn, :src, :status, :raw, CAST('{}' AS jsonb)) "
            "ON CONFLICT (id) DO NOTHING"
        ),
        {"id": faq_doc_id, "df": "f_faq", "fn": "faq_test.md",
         "src": "upload", "status": "PUBLISHED", "raw": "faq"},
    )
    # FAQ chunk with high-similarity embedding
    await db_session.execute(
        text(
            "INSERT INTO knowledge_chunks(document_id, chunk_index, content, embedding, metadata, category) "
            "VALUES (CAST(:did AS uuid), 0, :content, CAST(:e AS vector), CAST('{}' AS jsonb), 'faq') "
            "ON CONFLICT (document_id, chunk_index) DO UPDATE SET embedding = EXCLUDED.embedding, content = EXCLUDED.content"
        ),
        {"did": faq_doc_id, "content": "CANONICAL_FAQ_ANSWER: Lương từ 7-9 triệu", "e": good_vec},
    )
    # Regular (non-FAQ) chunk with same embedding
    await db_session.execute(
        text(
            "INSERT INTO knowledge_chunks(document_id, chunk_index, content, embedding, metadata, category) "
            "VALUES (CAST(:did AS uuid), 1, :content, CAST(:e AS vector), CAST('{}' AS jsonb), 'job') "
            "ON CONFLICT (document_id, chunk_index) DO UPDATE SET embedding = EXCLUDED.embedding, content = EXCLUDED.content"
        ),
        {"did": faq_doc_id, "content": "REGULAR_CHUNK_DATA", "e": good_vec},
    )
    await db_session.commit()

    out = await search_knowledge(db_session, emb, "Lương bao nhiêu")
    assert "CÂU HỎI THƯỜNG GẶP" in out
    assert "CANONICAL_FAQ_ANSWER" in out
    assert "REGULAR_CHUNK_DATA" in out
    # FAQ content appears before the regular chunk in the output
    assert out.index("CANONICAL_FAQ_ANSWER") < out.index("REGULAR_CHUNK_DATA")


# ---------------------------------------------------------------------------
# F4: greeting_gate allows numeric answers like "5" (age)
def test_greeting_gate_allows_numeric_answers():
    assert greeting_gate("5") is True
    assert greeting_gate("25") is True
    assert greeting_gate("30") is True


def test_greeting_gate_rejects_skip_list():
    assert greeting_gate("ok") is False
    assert greeting_gate("da") is False
    assert greeting_gate("👍") is False


def test_greeting_gate_rejects_empty_and_short_non_numeric():
    assert greeting_gate("") is False
    assert greeting_gate("a") is False
    assert greeting_gate("hi") is False  # len < 3 and not numeric
