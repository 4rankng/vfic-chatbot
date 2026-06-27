"""US-008 knowledge ingest + publish/archive/search/reconcile tests."""
import pytest
from sqlalchemy import text

from app.models.knowledge import KnowledgeStatus
from app.services.knowledge_service import KnowledgeService
from tests.conftest import ADMIN_EMAIL, PASSWORD

pytestmark = pytest.mark.asyncio


async def _admin_tok(client) -> str:
    r = await client.post("/api/v1/auth/login", json={"email": ADMIN_EMAIL, "password": PASSWORD})
    return r.json()["access_token"]


# `clean_kb` is provided by conftest.py (shared with test_jobs_dashboard).


async def _emb(_text):
    return [0.01] * 3072


async def test_upload_process_search_archive(client, db_session, clean_kb):
    svc = KnowledgeService(db_session)
    doc = await svc.upload("jobs.pdf", "LG Display tuyển công nhân lương 15 triệu", drive_file_id="f1")
    assert doc.status.value == "UPLOADED"

    # process: embeds 1 chunk, publishes it, rebuilds bus timetable (best-effort)
    doc = await svc.process(_emb, doc)
    assert doc.status == KnowledgeStatus.PUBLISHED
    n_chunks = (await db_session.execute(
        text("SELECT count(*) FROM knowledge_chunks WHERE document_id = :d"), {"d": str(doc.id)}
    )).scalar()
    assert n_chunks == 1

    # search surfaces it immediately after successful processing
    results = await svc.search_test(_emb, "LG Display", top_k=5)
    assert any("LG Display" in r["content"] for r in results)

    # an archived doc must NOT surface in search
    doc2 = await svc.upload("old.pdf", "tuyển bảo vệ", drive_file_id="f2")
    await svc.process(_emb, doc2)
    from types import SimpleNamespace

    admin_id = (await db_session.execute(text("SELECT id FROM users WHERE email=:e"), {"e": ADMIN_EMAIL})).scalar()
    await svc.archive(doc2, actor=SimpleNamespace(id=admin_id))
    res2 = await svc.search_test(_emb, "bảo vệ", top_k=5)
    assert all("bảo vệ" not in r["content"] for r in res2)


async def test_reconcile_drops_removed_files(db_session, clean_kb):
    svc = KnowledgeService(db_session)
    await svc.upload("keep.pdf", "a", drive_file_id="keep-1")
    await svc.upload("gone.pdf", "b", drive_file_id="gone-1")
    deleted = await svc.reconcile(["keep-1"])
    assert deleted == 1
    remaining = [d.drive_file_id for d in await svc.list()]
    assert "keep-1" in remaining and "gone-1" not in remaining


async def test_knowledge_api_admin_only(client, clean_kb):
    # no token -> 401; recruiter -> 403; admin -> 200
    assert (await client.get("/api/v1/knowledge/documents")).status_code == 401
    admin = await _admin_tok(client)
    h = {"Authorization": f"Bearer {admin}"}
    assert (await client.get("/api/v1/knowledge/documents", headers=h)).status_code == 200


async def test_knowledge_api_upload_archive(client, clean_kb):
    admin = await _admin_tok(client)
    h = {"Authorization": f"Bearer {admin}"}
    up = await client.post(
        "/api/v1/knowledge/documents/upload",
        json={"file_name": "x.pdf", "content": "nội dung", "drive_file_id": "api-f1"},
        headers=h,
    )
    assert up.status_code == 201
    doc_id = up.json()["id"]

    arch = await client.post(f"/api/v1/knowledge/documents/{doc_id}/archive", headers=h)
    assert arch.json()["status"] == "ARCHIVED"
