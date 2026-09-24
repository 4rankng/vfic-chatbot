"""Live-DB proof for the RAG ingestion pipeline and product-feature extraction.

Converted from the unit-lane modules that carried unconditional ``skip`` marks
(``tests/test_knowledge.py``, ``tests/test_product_features.py``, and the skipped
tail of ``tests/test_knowledge_pipeline.py``). They ran nowhere under ``skip``;
here they run against the disposable integration database with the LLM seam
injected as fakes, so the malformed-JSON retry branch, the 16-row extraction
invariant, and re-run idempotency execute real queries again.

The HTTP-level knowledge journey (upload endpoint, admin-only matrix, archive via
API) is deliberately not duplicated here — it is covered by the Playwright e2e
knowledge-upload spec driven through the real backend and real auth.
"""

from __future__ import annotations

import json
import uuid

import pytest
from sqlalchemy import text

from app.graph.tools import get_product_features
from app.models.company import Project
from app.models.knowledge import KnowledgeDocument, KnowledgeStatus
from app.models.user import Role, User
from app.services.knowledge import KnowledgePipeline, KnowledgeService

pytestmark = pytest.mark.integration

VEC = [0.01] * 3072


class _FakeEmbedder:
    async def embed(self, _t):
        return list(VEC)

    async def batch(self, texts):
        return [list(VEC) for _ in texts]

    __call__ = embed


def _units_payload(*contents):
    return {
        "document_summary": "tóm tắt",
        "units": [
            {
                "content": c,
                "source_quote": c,
                "summary": c[:30],
                "questions": [f"{c[:20]}?"],
                "category": "job",
                "entities": {},
                "source_anchor": "§1",
                "confidence": "high",
                "is_inference": False,
            }
            for c in contents
        ],
    }


def _features_payload():
    """LLM returns 3 features; the other 13 catalog features become is_missing=true."""
    return {
        "features": [
            {
                "feature_key": "take_home_income",
                "value_text": "10–13 triệu/tháng",
                "value_json": {
                    "min": 10000000,
                    "max": 13000000,
                    "currency": "VND",
                    "period": "month",
                },
                "is_highlight": True,
                "strength_score": 0.9,
                "evidence_text": "thu nhập 10-13 triệu",
            },
            {
                "feature_key": "pay_frequency",
                "value_text": "Trả lương theo tuần",
                "is_highlight": True,
                "strength_score": 0.95,
            },
            {
                "feature_key": "commute_support",
                "value_text": "Có xe đưa đón Thái Bình",
                "is_highlight": False,
                "strength_score": 0.7,
            },
        ]
    }


async def _seed_project(db) -> Project:
    proj = Project(slug=f"lg-{uuid.uuid4().hex[:6]}", name="LG Display", is_active=True)
    db.add(proj)
    await db.commit()
    await db.refresh(proj)
    return proj


async def _make_doc(db, raw, *, project_id=None):
    return await KnowledgeService(db).upload("kb.txt", raw, project_id=project_id)


def _count_features(db, project_id) -> ...:
    return db.execute(
        text("SELECT count(*) FROM job_feature_values WHERE project_id = :p"),
        {"p": str(project_id)},
    )


# ----------------------------------------------------------------- pipeline digest + retry
async def test_pipeline_run_marks_flagged_low_confidence(integration_session):
    doc = await _make_doc(integration_session, "sgiấy tờ không rõ.")

    async def llm_json(system, user):
        payload = _units_payload("thông tin suy luận")
        payload["units"][0]["confidence"] = "low"
        payload["units"][0]["is_inference"] = True
        return json.dumps(payload)

    await KnowledgePipeline(integration_session, _FakeEmbedder(), llm_json).run(doc)
    await integration_session.refresh(doc)
    assert doc.digest_meta["flagged_unit_indexes"] == [0]


async def test_pipeline_retries_on_malformed_then_succeeds(integration_session):
    doc = await _make_doc(integration_session, "nội dung bất kỳ")
    calls = {"n": 0}

    async def llm_json(system, user):
        calls["n"] += 1
        if calls["n"] == 1:
            return "<<<not json>>>"
        return json.dumps(_units_payload("đơn vị hợp lệ sau retry"))

    await KnowledgePipeline(integration_session, _FakeEmbedder(), llm_json).run(doc)
    assert calls["n"] == 2  # one malformed, one good
    await integration_session.refresh(doc)
    assert doc.status == KnowledgeStatus.PUBLISHED


async def test_pipeline_falls_back_after_repeated_malformed_digests(integration_session):
    """Both malformed digests are retried once, then the doc still publishes with
    source-grounded fallback units instead of dying at zero."""
    doc = await _make_doc(integration_session, "LG Display tuyển vị trí operator")
    calls = {"n": 0}

    async def llm_json(system, user):
        calls["n"] += 1
        return "still not json"

    await KnowledgePipeline(integration_session, _FakeEmbedder(), llm_json).run(doc)
    assert calls["n"] == 2  # one retry on malformed JSON, then the fallback
    await integration_session.refresh(doc)
    assert doc.status == KnowledgeStatus.PUBLISHED
    meta = doc.digest_meta or {}
    assert meta.get("unit_count", 0) >= 1
    content = (await integration_session.execute(
        text("SELECT content FROM knowledge_chunks WHERE document_id = :d"),
        {"d": str(doc.id)},
    )).scalars().all()
    assert content and all("LG Display" in c for c in content)


async def test_mechanical_fallback_one_chunk(integration_session):
    """process() without an llm_json keeps the legacy 1-chunk behaviour."""
    doc = await _make_doc(integration_session, "toàn bộ nội dung thành một chunk")
    doc = await KnowledgeService(integration_session).process(_FakeEmbedder(), doc)
    assert doc.status == KnowledgeStatus.PUBLISHED


# ----------------------------------------------------------------- project index + search
async def _seed_project_with_active_corpus(
    db, *, content: str, is_active: bool = True
) -> uuid.UUID:
    """Seed a project whose active KB version owns one embedded, published chunk.

    Search visibility and the master-index corpus are gated on
    ``kc.kb_version_id = p.active_kb_version_id`` — this seeds exactly that shape.
    """
    project_id = uuid.uuid4()
    version_id = uuid.uuid4()
    doc_id = uuid.uuid4()
    chunk_id = uuid.uuid4()
    emb = "[" + ",".join(["0.01"] * 3072) + "]"
    slug = f"lg-{uuid.uuid4().hex[:6]}"
    await db.execute(
        text(
            "INSERT INTO projects (id, slug, name, is_active) VALUES (:pid, :slug, 'LG Display', :act)"
        ),
        {"pid": str(project_id), "slug": slug, "act": is_active},
    )
    await db.execute(
        text(
            "INSERT INTO kb_versions (id, project_id, version_no, status) "
            "VALUES (:vid, :pid, 1, 'ACTIVE')"
        ),
        {"vid": str(version_id), "pid": str(project_id)},
    )
    await db.execute(
        text(
            "UPDATE projects SET active_kb_version_id = :vid WHERE id = :pid"
        ),
        {"vid": str(version_id), "pid": str(project_id)},
    )
    await db.execute(
        text(
            "INSERT INTO knowledge_documents (id, project_id, file_name, status, stage, source, raw_text) "
            "VALUES (:did, :pid, 'lg.txt', 'PUBLISHED', 'PUBLISHED', 'upload', :raw)"
        ),
        {"did": str(doc_id), "pid": str(project_id), "raw": content},
    )
    await db.execute(
        text(
            "INSERT INTO knowledge_chunks (id, document_id, kb_version_id, chunk_index, "
            "chunk_type, content, content_plain, token_count, embedding) "
            "VALUES (:cid, :did, :vid, 0, 'unit', :content, :content, 8, CAST(:emb AS vector))"
        ),
        {
            "cid": str(chunk_id),
            "did": str(doc_id),
            "vid": str(version_id),
            "content": content,
            "emb": emb,
        },
    )
    await db.commit()
    return project_id


async def test_build_project_index_card_feeds_from_the_active_kb_version(integration_session):
    project_id = await _seed_project_with_active_corpus(
        integration_session, content="LG Display tuyển operator"
    )

    async def llm_json(system, user):
        return json.dumps(
            {
                "summary": "Nhà máy LG Display",
                "key_roles": ["operator"],
                "location": "Hải Phòng",
                "highlights": ["lương cao"],
            }
        )

    await KnowledgePipeline(integration_session, _FakeEmbedder(), llm_json).build_project_index(
        project_id
    )
    row = (
        await integration_session.execute(
            text("SELECT summary, index_card FROM projects WHERE id = :pid"),
            {"pid": str(project_id)},
        )
    ).first()
    assert row.summary == "Nhà máy LG Display"
    assert row.index_card["key_roles"] == ["operator"]


async def test_search_test_scoped_to_project(integration_session):
    p_in = await _seed_project_with_active_corpus(
        integration_session, content="LG Display tuyển operator"
    )
    await _seed_project_with_active_corpus(
        integration_session, content="Samsung tuyển thợ điện"
    )

    svc = KnowledgeService(integration_session)
    scoped = await svc.search_test(_FakeEmbedder(), "tuyển", top_k=10, project_id=p_in)
    assert [r["content"] for r in scoped] and all("LG Display" in r["content"] for r in scoped)
    assert all("Samsung" not in r["content"] for r in scoped)

    everything = await svc.search_test(_FakeEmbedder(), "tuyển", top_k=10)
    contents = [r["content"] for r in everything]
    assert any("LG Display" in c for c in contents)
    assert any("Samsung" in c for c in contents)


async def test_archived_document_drops_out_of_search(integration_session):
    project_id = await _seed_project_with_active_corpus(
        integration_session, content="LG Display tuyển công nhân lương 15 triệu"
    )
    svc = KnowledgeService(integration_session)

    found = await svc.search_test(_FakeEmbedder(), "LG Display", top_k=5)
    assert any("lương 15 triệu" in r["content"] for r in found)

    admin = User(
        email=f"archiver-{uuid.uuid4().hex}@example.test",
        password_hash="not-used",
        role=Role.admin,
    )
    integration_session.add(admin)
    await integration_session.flush()
    doc = await integration_session.get_one(
        KnowledgeDocument, await _only_document_id(integration_session, project_id)
    )
    await svc.archive(doc, actor=admin)

    res2 = await svc.search_test(_FakeEmbedder(), "LG Display", top_k=5)
    assert all("lương 15 triệu" not in r["content"] for r in res2)


async def _only_document_id(db, project_id) -> str:
    return (
        await db.execute(
            text("SELECT id FROM knowledge_documents WHERE project_id = :pid"),
            {"pid": str(project_id)},
        )
    ).scalar_one()


async def test_reconcile_drops_removed_files(integration_session):
    svc = KnowledgeService(integration_session)
    await svc.upload("keep.pdf", "a", drive_file_id="keep-1")
    await svc.upload("gone.pdf", "b", drive_file_id="gone-1")
    deleted = await svc.reconcile(["keep-1"])
    assert deleted == 1
    docs, _total = await svc.list()
    remaining = [d.drive_file_id for d in docs]
    assert "keep-1" in remaining and "gone-1" not in remaining


# ----------------------------------------------------------------- product-feature extraction
async def test_extract_writes_one_row_per_active_catalog_feature(integration_session):
    proj = await _seed_project(integration_session)
    doc = await _make_doc(
        integration_session, "LG Display tuyển operator lương 10-13 triệu.", project_id=proj.id
    )

    async def llm_json(system, user):
        return json.dumps(_features_payload())

    await KnowledgePipeline(integration_session, _FakeEmbedder(), llm_json).extract_product_features(
        doc, []
    )

    n = (await _count_features(integration_session, proj.id)).scalar()
    catalog_rows = (
        await integration_session.execute(
            text("SELECT count(*) FROM worker_feature_catalog WHERE is_active")
        )
    ).scalar()
    assert n == catalog_rows  # one row per active catalog feature, whatever the catalog size

    hi = (
        await integration_session.execute(
            text(
                "SELECT jfv.is_highlight, jfv.is_missing, jfv.value_json, jfv.evidence_text "
                "FROM job_feature_values jfv "
                "WHERE jfv.project_id = :p AND jfv.evidence_text = 'thu nhập 10-13 triệu'"
            ),
            {"p": str(proj.id)},
        )
    ).first()
    assert hi is not None and hi.is_highlight is True and hi.is_missing is False
    assert hi.value_json["max"] == 13000000

    miss = (
        await integration_session.execute(
            text(
                "SELECT jfv.is_missing, jfv.value_text FROM job_feature_values jfv "
                "WHERE jfv.project_id = :p AND jfv.is_missing"
            ),
            {"p": str(proj.id)},
        )
    ).first()
    assert miss is not None
    assert "chưa ghi rõ" in miss.value_text


async def test_extract_is_idempotent_on_rerun(integration_session):
    proj = await _seed_project(integration_session)
    doc = await _make_doc(integration_session, "LG Display.", project_id=proj.id)

    async def llm_json(system, user):
        return json.dumps(_features_payload())

    pipe = KnowledgePipeline(integration_session, _FakeEmbedder(), llm_json)
    await pipe.extract_product_features(doc, [])
    await pipe.extract_product_features(doc, [])  # re-extract: delete-then-insert

    n = (await _count_features(integration_session, proj.id)).scalar()
    catalog_rows = (
        await integration_session.execute(
            text("SELECT count(*) FROM worker_feature_catalog WHERE is_active")
        )
    ).scalar()
    assert n == catalog_rows  # re-extract deletes then re-inserts: no duplicates


async def test_extract_syncs_project_highlights(integration_session):
    proj = await _seed_project(integration_session)
    doc = await _make_doc(integration_session, "LG Display.", project_id=proj.id)

    async def llm_json(system, user):
        return json.dumps(_features_payload())

    await KnowledgePipeline(integration_session, _FakeEmbedder(), llm_json).extract_product_features(
        doc, []
    )
    await integration_session.refresh(proj)
    highlights = proj.index_card.get("highlights") or []
    assert any("10–13 triệu" in h for h in highlights)
    assert any("tuần" in h for h in highlights)


async def test_pipeline_run_extracts_features(integration_session):
    proj = await _seed_project(integration_session)
    doc = await _make_doc(
        integration_session,
        "LG Display tuyển operator lương 10-13 triệu trả theo tuần.",
        project_id=proj.id,
    )

    async def llm_json(system, user):
        # Distinguish the extraction call (PRODUCT_FEATURE_SYSTEM_PROMPT) from digest.
        if "feature_key" in system:
            return json.dumps(_features_payload())
        return json.dumps(_units_payload("LG Display tuyển operator."))

    await KnowledgePipeline(integration_session, _FakeEmbedder(), llm_json).run(doc)
    await integration_session.refresh(doc)

    assert doc.status == KnowledgeStatus.PUBLISHED
    catalog_rows = (
        await integration_session.execute(
            text("SELECT count(*) FROM worker_feature_catalog WHERE is_active")
        )
    ).scalar()
    assert (await _count_features(integration_session, proj.id)).scalar() == catalog_rows


async def test_pipeline_run_survives_bad_extraction(integration_session):
    """A malformed extraction response must not block RAG indexing (best-effort)."""
    proj = await _seed_project(integration_session)
    doc = await _make_doc(integration_session, "nội dung bất kỳ", project_id=proj.id)

    async def llm_json(system, user):
        if "feature_key" in system:
            return "<<<not json>>>"  # extraction fails
        return json.dumps(_units_payload("đơn vị hợp lệ"))

    await KnowledgePipeline(integration_session, _FakeEmbedder(), llm_json).run(doc)
    await integration_session.refresh(doc)

    assert doc.status == KnowledgeStatus.PUBLISHED  # ingest NOT blocked
    assert (await _count_features(integration_session, proj.id)).scalar() == 0  # nothing written


# ----------------------------------------------------------------- agent tool
async def test_get_product_features_tool(integration_session, monkeypatch):
    proj = await _seed_project(integration_session)
    doc = await _make_doc(integration_session, "LG Display.", project_id=proj.id)

    async def llm_json(system, user):
        return json.dumps(_features_payload())

    await KnowledgePipeline(integration_session, _FakeEmbedder(), llm_json).extract_product_features(
        doc, []
    )

    # project_id_by_slug only resolves projects managed through a knowledge base;
    # link the seeded legacy project to one so the tool can resolve it.
    kb_id = uuid.uuid4()
    await integration_session.execute(
        text("INSERT INTO knowledge_bases (id, slug, name, mode) VALUES (:kid, :slug, 'KB', 'RAG')"),
        {"kid": str(kb_id), "slug": f"kb-{uuid.uuid4().hex[:6]}"},
    )
    await integration_session.execute(
        text("UPDATE projects SET knowledge_base_id = :kid WHERE id = :pid"),
        {"kid": str(kb_id), "pid": str(proj.id)},
    )
    await integration_session.commit()

    # The tool caches its formatted result in Redis; bypass so the run is hermetic.
    import app.graph.tools.catalog as catalog_module
    from app.services.retrieval.catalog_repository import CatalogRepository

    async def _no_cache_version(_ns):
        return "0"

    async def _no_cache_get(_key):
        return None

    async def _no_cache_set(_key, _value, _ttl=None):
        return None

    monkeypatch.setattr(catalog_module, "cache_version", _no_cache_version)
    monkeypatch.setattr(catalog_module, "cache_get_json", _no_cache_get)
    monkeypatch.setattr(catalog_module, "cache_set_json", _no_cache_set)

    repo = CatalogRepository(integration_session, page_project_ids=None)
    out = await get_product_features(repo, proj.slug)
    assert "Đặc điểm sản phẩm" in out
    assert "10–13 triệu/tháng" in out
    assert "NỔI BẬT" in out  # highlighted feature flagged for the agent
    assert "chưa ghi rõ" in out  # missing feature surfaced honestly
    assert "QUY TẮC" in out  # strict no-invent reminder

    miss = await get_product_features(repo, "does-not-exist-slug")
    assert "Không tìm thấy" in miss
