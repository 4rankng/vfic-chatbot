"""LLM training-pipeline tests (US: per-project KB upload + digestion + personas).

Exercises KnowledgePipeline with INJECTED fakes (no MiniMax/Gemini keys): raw-text
upload decode, digest schema validation + retry-on-malformed, the full run() (digest ->
embed -> index) writing rich chunks, project index-card build, scoped search, and the
multipart upload-file endpoint (with enqueue stubbed).
"""
import asyncio
import json
import uuid
from types import SimpleNamespace

import pytest
from sqlalchemy import text

from app.models.company import Project
from app.models.knowledge import KnowledgeDocument, KnowledgeStatus
from app.services.knowledge import (
    DigestError,
    KnowledgePipeline,
    split_for_digest,
    validate_digest,
)
from app.services.knowledge_service import KnowledgeService
from tests.conftest import ADMIN_EMAIL, PASSWORD

pytestmark = pytest.mark.asyncio

VEC = [0.01] * 3072


class _FakeEmbedder:
    """GeminiEmbedder-compatible: embed + batch + __call__."""

    async def embed(self, _t):
        return list(VEC)

    async def batch(self, texts):
        return [list(VEC) for _ in texts]

    __call__ = embed


def _units_payload(*contents):
    return {
        "document_summary": "tóm tắt tài liệu",
        "units": [
            {
                "content": c,
                "source_quote": c,
                "summary": c[:30],
                "questions": [f"{c[:20]}?"],
                "category": "job",
                "entities": {"job_title": "operator", "location": "Hải Phòng"},
                "source_anchor": "§1",
                "confidence": "high",
                "is_inference": False,
            }
            for c in contents
        ],
    }


def test_split_for_digest_respects_size():
    big = "x" * 15000
    sections = split_for_digest(big, max_chars=6000)
    assert len(sections) >= 2 and all(len(s) <= 6000 for s in sections)
    assert split_for_digest("", 6000) == []
    assert split_for_digest("ngắn", 6000) == ["ngắn"]


# --------------------------------------------------------------------------- validate
def test_validate_digest_happy_and_coercion():
    summary, units = validate_digest(
        {"document_summary": "s", "units": [{"content": "c", "category": "WEIRD", "confidence": "nope"}]}
    )
    assert summary == "s" and len(units) == 1
    u = units[0]
    assert u["category"] == "other" and u["confidence"] == "medium" and u["questions"] == []


def test_validate_digest_rejects_malformed():
    with pytest.raises(DigestError):
        validate_digest({"document_summary": "s"})  # no units
    with pytest.raises(DigestError):
        validate_digest({"units": [{"summary": "no content"}]})  # unit missing content
    with pytest.raises(DigestError):
        validate_digest("not an object")


# --------------------------------------------------------------------------- pipeline.run
async def _make_doc(db, raw, *, project_id=None):
    svc = KnowledgeService(db)
    return await svc.upload("kb.txt", raw, project_id=project_id)


async def test_pipeline_run_writes_rich_chunks(db_session, clean_kb):
    doc = await _make_doc(db_session, "LG Display tuyển operator ca đêm lương 10 triệu ở Hải Phòng.")

    async def llm_json(system, user):
        return json.dumps(_units_payload("LG Display Hải Phòng tuyển operator ca đêm lương 10 triệu."))

    await KnowledgePipeline(db_session, _FakeEmbedder(), llm_json).run(doc)
    await db_session.refresh(doc)

    assert doc.status == KnowledgeStatus.PUBLISHED
    assert doc.stage == "PUBLISHED"
    assert doc.digest_meta["unit_count"] == 1
    assert doc.digest_meta["flagged_unit_indexes"] == []
    rows = (
        await db_session.execute(
            text(
                "SELECT content, category, confidence, cardinality(questions) AS nq, source_quote "
                "FROM knowledge_chunks WHERE document_id = :d ORDER BY chunk_index"
            ),
            {"d": str(doc.id)},
        )
    ).all()
    assert len(rows) == 1
    assert rows[0].category == "job" and rows[0].confidence == "high" and rows[0].nq == 1
    assert rows[0].source_quote is not None


async def test_pipeline_run_marks_flagged_low_confidence(db_session, clean_kb):
    doc = await _make_doc(db_session, "sgiấy tờ không rõ.")

    async def llm_json(system, user):
        payload = _units_payload("thông tin suy luận")
        payload["units"][0]["confidence"] = "low"
        payload["units"][0]["is_inference"] = True
        return json.dumps(payload)

    await KnowledgePipeline(db_session, _FakeEmbedder(), llm_json).run(doc)
    await db_session.refresh(doc)
    assert doc.digest_meta["flagged_unit_indexes"] == [0]


async def test_pipeline_retries_on_malformed_then_succeeds(db_session, clean_kb):
    doc = await _make_doc(db_session, "nội dung bất kỳ")
    calls = {"n": 0}

    async def llm_json(system, user):
        calls["n"] += 1
        if calls["n"] == 1:
            return "<<<not json>>>"
        return json.dumps(_units_payload("đơn vị hợp lệ sau retry"))

    await KnowledgePipeline(db_session, _FakeEmbedder(), llm_json).run(doc)
    assert calls["n"] == 2  # one malformed, one good
    await db_session.refresh(doc)
    assert doc.status == KnowledgeStatus.PUBLISHED


async def test_pipeline_falls_back_after_retry_failure(db_session, clean_kb):
    doc = await _make_doc(db_session, "nội dung")

    async def llm_json(system, user):
        return "still not json"

    await KnowledgePipeline(db_session, _FakeEmbedder(), llm_json).run(doc)

    await db_session.refresh(doc)
    assert doc.status == KnowledgeStatus.PUBLISHED
    assert doc.digest_meta["unit_count"] == 1
    rows = (
        await db_session.execute(
            text("SELECT content, source_quote FROM knowledge_chunks WHERE document_id = :d"),
            {"d": str(doc.id)},
        )
    ).all()
    assert rows[0].source_quote == "nội dung"


async def test_ingest_worker_crash_marks_document_failed(db_session, clean_kb):
    from app.workers.ingest_worker import _mark_doc_failed_sync

    doc = await _make_doc(db_session, "nội dung")
    doc.status = KnowledgeStatus.PROCESSING
    doc.stage = "DIGESTING"
    await db_session.commit()

    _mark_doc_failed_sync(str(doc.id), TimeoutError("rq timeout"))

    await db_session.refresh(doc)
    assert doc.status == KnowledgeStatus.FAILED
    assert doc.stage == "FAILED"
    assert "TimeoutError: rq timeout" in (doc.error or "")


async def test_ingest_job_marks_document_failed_when_digest_times_out(
    db_session, clean_kb, monkeypatch
):
    from app.services.knowledge import pipeline as pipeline_module
    from app.workers.ingest_worker import _run_job_async

    doc = await _make_doc(db_session, "nội dung khiến MiniMax treo")
    await db_session.commit()
    monkeypatch.setattr(
        pipeline_module,
        "get_settings",
        lambda: SimpleNamespace(minimax_request_timeout=0.01),
    )

    async def hanging_llm(system, user):
        await asyncio.sleep(10)
        return json.dumps(_units_payload("không bao giờ tới đây"))

    await _run_in_fresh_loop(
        lambda: _run_job_async(str(doc.id), _embed=_FakeEmbedder(), _llm=hanging_llm)
    )

    await db_session.refresh(doc)
    assert doc.status == KnowledgeStatus.FAILED
    assert doc.stage == "FAILED"
    assert "MiniMax digest timed out after 0.01s" in (doc.error or "")


async def _run_in_fresh_loop(factory):
    """Run ``factory()`` via ``asyncio.run`` in a worker thread.

    Each call gets a fresh, isolated event loop — mirroring how RQ's SimpleWorker runs
    each job (``asyncio.run`` per job). ``asyncio.run`` cannot be called directly inside
    an async test because pytest-asyncio already has a loop running, so we hop to a
    worker thread which has no running loop.
    """
    import asyncio
    from concurrent.futures import ThreadPoolExecutor

    loop = asyncio.get_running_loop()

    def _sync() -> None:
        asyncio.run(factory())

    with ThreadPoolExecutor(max_workers=1) as ex:
        await loop.run_in_executor(ex, _sync)


async def test_worker_session_is_loop_safe_across_jobs():
    """Two consecutive fresh event loops using worker_session() must not raise
    'Future attached to a different loop', and the module-global engine must still
    serve a query afterward — proves the per-job NullPool helper does not disturb the
    web app's engine. Covers all four adoption sites at once (they share the helper)."""
    from app.core import db as db_module
    from app.workers._db import worker_session

    async def _helper() -> None:
        async with worker_session() as s:
            await s.execute(text("SELECT 1"))

    async def _global() -> None:
        async with db_module.async_session() as s:
            await s.execute(text("SELECT 1"))

    await _run_in_fresh_loop(_helper)
    await _run_in_fresh_loop(_helper)  # second fresh loop reuses nothing
    await _run_in_fresh_loop(_global)  # web-app invariant: global engine still serves a query


async def test_ingest_job_runs_twice_across_loops(db_session, clean_kb):
    """The full ingest pipeline runs twice across two fresh event loops (fakes injected)
    without a cross-loop error and reaches PUBLISHED — the RC2 regression that previously
    killed every retry in 0.025s."""
    from app.workers.ingest_worker import _run_job_async

    doc = await _make_doc(db_session, "LG Display tuyển operator ca đêm lương 10 triệu.")
    await db_session.commit()

    async def fake_llm(system, user):
        return json.dumps(_units_payload("LG Display Hải Phòng tuyển operator ca đêm."))

    embed = _FakeEmbedder()
    await _run_in_fresh_loop(lambda: _run_job_async(str(doc.id), _embed=embed, _llm=fake_llm))
    await _run_in_fresh_loop(lambda: _run_job_async(str(doc.id), _embed=embed, _llm=fake_llm))

    await db_session.refresh(doc)
    assert doc.status == KnowledgeStatus.PUBLISHED


async def test_mechanical_fallback_one_chunk(db_session, clean_kb):
    """process() without an llm_json keeps the legacy 1-chunk behaviour."""
    doc = await _make_doc(db_session, "toàn bộ nội dung thành một chunk")
    doc = await KnowledgeService(db_session).process(_FakeEmbedder(), doc)
    n = (
        await db_session.execute(
            text("SELECT count(*) FROM knowledge_chunks WHERE document_id = :d"), {"d": str(doc.id)}
        )
    ).scalar()
    assert n == 1 and doc.status == KnowledgeStatus.PUBLISHED


# --------------------------------------------------------------------------- project index
async def _seed_project(db):
    proj = Project(slug=f"lg-{uuid.uuid4().hex[:6]}", name="LG Display", is_active=True)
    db.add(proj)
    await db.commit()
    await db.refresh(proj)
    return proj


async def test_build_project_index_card(db_session, clean_kb):
    proj = await _seed_project(db_session)
    svc = KnowledgeService(db_session)
    doc = await svc.upload("lg.txt", "LG Display tuyển operator", project_id=proj.id)
    await svc.process(_FakeEmbedder(), doc)  # chunk it

    async def llm_json(system, user):
        return json.dumps({"summary": "Nhà máy LG Display", "key_roles": ["operator"], "location": "Hải Phòng", "highlights": ["lương cao"]})

    await KnowledgePipeline(db_session, _FakeEmbedder(), llm_json).build_project_index(proj.id)
    await db_session.refresh(proj)
    assert proj.summary == "Nhà máy LG Display"
    assert proj.index_card["key_roles"] == ["operator"]


async def test_search_test_scoped_to_project(db_session, clean_kb):
    proj = await _seed_project(db_session)
    svc = KnowledgeService(db_session)
    d_in = await svc.upload("in.txt", "LG Display tuyển operator", project_id=proj.id)
    d_out = await svc.upload("out.txt", "Samsung tuyển thợ điện")  # project_id NULL
    await svc.process(_FakeEmbedder(), d_in)
    await svc.process(_FakeEmbedder(), d_out)

    scoped = await svc.search_test(_FakeEmbedder(), "tuyển", top_k=10, project_id=proj.id)
    assert any("LG Display" in r["content"] for r in scoped)
    assert all("Samsung" not in r["content"] for r in scoped)


# --------------------------------------------------------------------------- multipart API
async def test_upload_file_endpoint_decodes_text_and_enqueues(client, db_session, clean_kb, monkeypatch):
    # Stub enqueue so the test doesn't drop a real job onto the RQ queue.
    enqueued: list[str] = []
    monkeypatch.setattr(
        "app.api.knowledge.enqueue_ingest", lambda doc_id: enqueued.append(str(doc_id))
    )
    tok = (
        await client.post("/api/v1/auth/login", json={"email": ADMIN_EMAIL, "password": PASSWORD})
    ).json()["access_token"]
    h = {"Authorization": f"Bearer {tok}"}

    # Uploads are raw text now (no Office parsing): send Vietnamese UTF-8 bytes as a .txt.
    payload = "Nội dung text LG Display — lương 10 triệu".encode("utf-8")

    r = await client.post(
        "/api/v1/knowledge/documents/upload-file",
        files={"file": ("lg.txt", payload, "text/plain")},
        headers=h,
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["stage"] in {"EXTRACTED", "UPLOADED"}
    assert len(enqueued) == 1 and enqueued[0] == body["id"]
    # raw_text is decoded verbatim from the uploaded bytes and persisted on the doc
    doc = await db_session.get(KnowledgeDocument, uuid.UUID(body["id"]))
    assert doc is not None and "LG Display" in (doc.raw_text or "")
