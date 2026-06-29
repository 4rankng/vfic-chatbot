"""Worker product-feature tests: the active-feature extraction step + agent tool.

Exercises KnowledgePipeline.extract_product_features with an injected fake LLM (no
MiniMax key): one row per active catalog feature,
highlight/missing/value_json coercion, idempotent re-run, best-effort (never blocks
ingest), and the get_product_features agent tool (structured, non-RAG — precedent:
search_bus_timetable).
"""
import json
import uuid

import pytest
import pytest_asyncio
from sqlalchemy import text

from app.graph.tools import get_product_features
from app.models.company import Project
from app.models.knowledge import KnowledgeStatus
from app.services.knowledge import KnowledgePipeline
from app.services.knowledge_service import KnowledgeService
from tests.conftest import PASSWORD, RECRUITER_EMAIL

pytestmark = pytest.mark.asyncio


class _FakeEmbedder:
    async def embed(self, _t):
        return [0.01] * 3072

    async def batch(self, texts):
        return [[0.01] * 3072 for _ in texts]

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
    """LLM returns 3 features; the other 9 active catalog features become is_missing=true."""
    return {
        "features": [
            {
                "feature_key": "take_home_income",
                "value_text": "10–13 triệu/tháng",
                "value_json": {"min": 10000000, "max": 13000000, "currency": "VND", "period": "month"},
                "is_highlight": True,
                "strength_score": 0.9,
                "evidence_text": "thu nhập 10-13 triệu",
            },
            {"feature_key": "pay_frequency", "value_text": "Trả lương theo tuần", "is_highlight": True, "strength_score": 0.95},
            {"feature_key": "commute_support", "value_text": "Có xe đưa đón Thái Bình", "is_highlight": False, "strength_score": 0.7},
        ]
    }


@pytest_asyncio.fixture
async def clean_features(db_session):
    """job_feature_values are per-project and accumulate across runs; wipe them.

    worker_feature_catalog (the 12-active seed) is deliberately NOT truncated — tests
    rely on those rows being present.
    """
    await db_session.execute(text("TRUNCATE job_feature_values"))
    await db_session.commit()
    yield
    await db_session.execute(text("TRUNCATE job_feature_values"))
    await db_session.commit()


async def _seed_project(db):
    proj = Project(slug=f"lg-{uuid.uuid4().hex[:6]}", name="LG Display", is_active=True)
    db.add(proj)
    await db.commit()
    await db.refresh(proj)
    return proj


async def _make_doc(db, raw, *, project_id=None):
    return await KnowledgeService(db).upload("kb.txt", raw, project_id=project_id)


def _count_features(db, project_id) -> ...:
    return db.execute(
        text("SELECT count(*) FROM job_feature_values WHERE project_id = :p"), {"p": str(project_id)}
    )


# --------------------------------------------------------------------------- extraction
async def test_extract_writes_exactly_12_rows(db_session, clean_kb, clean_features):
    proj = await _seed_project(db_session)
    doc = await _make_doc(db_session, "LG Display tuyển operator lương 10-13 triệu.", project_id=proj.id)

    async def llm_json(system, user):
        return json.dumps(_features_payload())

    await KnowledgePipeline(db_session, _FakeEmbedder(), llm_json).extract_product_features(doc, [])

    n = (await _count_features(db_session, proj.id)).scalar()
    assert n == 12  # one row per catalog feature, regardless of how many the LLM returned

    hi = (
        await db_session.execute(
            text(
                "SELECT jfv.is_highlight, jfv.is_missing, jfv.value_json, jfv.evidence_text "
                "FROM job_feature_values jfv JOIN worker_feature_catalog wfc ON wfc.id = jfv.feature_id "
                "WHERE jfv.project_id = :p AND wfc.feature_key = 'take_home_income'"
            ),
            {"p": str(proj.id)},
        )
    ).first()
    assert hi.is_highlight is True and hi.is_missing is False
    assert hi.value_json["max"] == 13000000
    assert hi.evidence_text == "thu nhập 10-13 triệu"

    miss = (
        await db_session.execute(
            text(
                "SELECT jfv.is_missing, jfv.value_text FROM job_feature_values jfv "
                "JOIN worker_feature_catalog wfc ON wfc.id = jfv.feature_id "
                "WHERE jfv.project_id = :p AND wfc.feature_key = 'housing'"
            ),
            {"p": str(proj.id)},
        )
    ).first()
    assert miss.is_missing is True
    assert "chưa ghi rõ" in miss.value_text


async def test_extract_is_idempotent_on_rerun(db_session, clean_kb, clean_features):
    proj = await _seed_project(db_session)
    doc = await _make_doc(db_session, "LG Display.", project_id=proj.id)

    async def llm_json(system, user):
        return json.dumps(_features_payload())

    pipe = KnowledgePipeline(db_session, _FakeEmbedder(), llm_json)
    await pipe.extract_product_features(doc, [])
    await pipe.extract_product_features(doc, [])  # re-extract: delete-then-insert

    n = (await _count_features(db_session, proj.id)).scalar()
    assert n == 12  # no duplicates


async def test_new_upload_merges_features_without_erasing_existing_values(
    db_session, clean_kb, clean_features
):
    proj = await _seed_project(db_session)
    first_doc = await _make_doc(
        db_session,
        "LG Display tuyển operator lương 10-13 triệu, có xe đưa đón Thái Bình.",
        project_id=proj.id,
    )
    second_doc = await _make_doc(
        db_session,
        "LG Display cập nhật thu nhập 12-15 triệu/tháng.",
        project_id=proj.id,
    )

    async def first_llm_json(system, user):
        return json.dumps(_features_payload())

    async def second_llm_json(system, user):
        return json.dumps(
            {
                "features": [
                    {
                        "feature_key": "take_home_income",
                        "value_text": "12–15 triệu/tháng",
                        "value_json": {
                            "min": 12000000,
                            "max": 15000000,
                            "currency": "VND",
                            "period": "month",
                        },
                        "is_highlight": True,
                        "strength_score": 0.92,
                        "evidence_text": "thu nhập 12-15 triệu",
                    }
                ]
            }
        )

    await KnowledgePipeline(db_session, _FakeEmbedder(), first_llm_json).extract_product_features(
        first_doc, []
    )
    await KnowledgePipeline(db_session, _FakeEmbedder(), second_llm_json).extract_product_features(
        second_doc, []
    )

    rows = (
        await db_session.execute(
            text(
                "SELECT wfc.feature_key, jfv.value_text, jfv.value_json, "
                "jfv.is_missing, jfv.source_document_id "
                "FROM job_feature_values jfv "
                "JOIN worker_feature_catalog wfc ON wfc.id = jfv.feature_id "
                "WHERE jfv.project_id = :p "
                "AND wfc.feature_key IN ('take_home_income', 'commute_support')"
            ),
            {"p": str(proj.id)},
        )
    ).mappings()
    by_key = {row["feature_key"]: row for row in rows}

    assert by_key["take_home_income"]["value_text"] == "12–15 triệu/tháng"
    assert by_key["take_home_income"]["value_json"]["max"] == 15000000
    assert by_key["take_home_income"]["source_document_id"] == second_doc.id

    assert by_key["commute_support"]["value_text"] == "Có xe đưa đón Thái Bình"
    assert by_key["commute_support"]["is_missing"] is False
    assert by_key["commute_support"]["source_document_id"] == first_doc.id
    assert (await _count_features(db_session, proj.id)).scalar() == 12


async def test_extract_syncs_project_highlights(db_session, clean_kb, clean_features):
    proj = await _seed_project(db_session)
    doc = await _make_doc(db_session, "LG Display.", project_id=proj.id)

    async def llm_json(system, user):
        return json.dumps(_features_payload())

    await KnowledgePipeline(db_session, _FakeEmbedder(), llm_json).extract_product_features(doc, [])
    await db_session.refresh(proj)
    highlights = proj.index_card.get("highlights") or []
    assert any("10–13 triệu" in h for h in highlights)
    assert any("tuần" in h for h in highlights)


# --------------------------------------------------------------------------- run() integration
async def test_pipeline_run_extracts_features(db_session, clean_kb, clean_features):
    proj = await _seed_project(db_session)
    doc = await _make_doc(
        db_session, "LG Display tuyển operator lương 10-13 triệu trả theo tuần.", project_id=proj.id
    )

    async def llm_json(system, user):
        # Distinguish the extraction call (PRODUCT_FEATURE_SYSTEM_PROMPT) from digest.
        if "feature_key" in system:
            return json.dumps(_features_payload())
        return json.dumps(_units_payload("LG Display tuyển operator."))

    await KnowledgePipeline(db_session, _FakeEmbedder(), llm_json).run(doc)
    await db_session.refresh(doc)

    assert doc.status == KnowledgeStatus.PUBLISHED
    assert (await _count_features(db_session, proj.id)).scalar() == 12


async def test_pipeline_run_survives_bad_extraction(db_session, clean_kb, clean_features):
    """A malformed extraction response must not block RAG indexing (best-effort)."""
    proj = await _seed_project(db_session)
    doc = await _make_doc(db_session, "nội dung bất kỳ", project_id=proj.id)

    async def llm_json(system, user):
        if "feature_key" in system:
            return "<<<not json>>>"  # extraction fails
        return json.dumps(_units_payload("đơn vị hợp lệ"))

    await KnowledgePipeline(db_session, _FakeEmbedder(), llm_json).run(doc)
    await db_session.refresh(doc)

    assert doc.status == KnowledgeStatus.PUBLISHED  # ingest NOT blocked
    assert (await _count_features(db_session, proj.id)).scalar() == 0  # nothing written


# --------------------------------------------------------------------------- agent tool
async def test_get_product_features_tool(db_session, clean_kb, clean_features):
    proj = await _seed_project(db_session)
    doc = await _make_doc(db_session, "LG Display.", project_id=proj.id)

    async def llm_json(system, user):
        return json.dumps(_features_payload())

    await KnowledgePipeline(db_session, _FakeEmbedder(), llm_json).extract_product_features(doc, [])

    out = await get_product_features(db_session, proj.slug)
    assert "Đặc điểm sản phẩm" in out
    assert "10–13 triệu/tháng" in out
    assert "NỔI BẬT" in out  # highlighted feature flagged for the agent
    assert "chưa ghi rõ" in out  # missing feature surfaced honestly
    assert "QUY TẮC" in out  # strict no-invent reminder

    miss = await get_product_features(db_session, "does-not-exist-slug")
    assert "Không tìm thấy" in miss


async def test_recruiter_can_read_project_features_api(client, db_session, clean_kb, clean_features):
    proj = await _seed_project(db_session)
    doc = await _make_doc(db_session, "LG Display.", project_id=proj.id)

    async def llm_json(system, user):
        return json.dumps(_features_payload())

    await KnowledgePipeline(db_session, _FakeEmbedder(), llm_json).extract_product_features(doc, [])

    token = (
        await client.post(
            "/api/v1/auth/login",
            json={"email": RECRUITER_EMAIL, "password": PASSWORD},
        )
    ).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    listed = await client.get("/api/v1/knowledge/projects", headers=headers)
    assert listed.status_code == 200
    assert any(p["id"] == str(proj.id) for p in listed.json()["data"])

    one = await client.get(f"/api/v1/knowledge/projects/{proj.id}", headers=headers)
    assert one.status_code == 200
    assert one.json()["id"] == str(proj.id)

    project_edit = await client.patch(
        f"/api/v1/knowledge/projects/{proj.id}",
        json={"name": "LG Display Recruiter Updated"},
        headers=headers,
    )
    assert project_edit.status_code == 200
    assert project_edit.json()["name"] == "LG Display Recruiter Updated"

    features = await client.get(f"/api/v1/knowledge/projects/{proj.id}/features", headers=headers)
    assert features.status_code == 200
    body = features.json()
    assert body["total"] == 12
    feature_id = body["data"][0]["id"]

    edit = await client.patch(
        f"/api/v1/knowledge/projects/{proj.id}/features/{feature_id}",
        json={"value_text": "Nhân viên tuyển dụng đã cập nhật nội dung tư vấn."},
        headers=headers,
    )
    assert edit.status_code == 200
    assert edit.json()["value_text"] == "Nhân viên tuyển dụng đã cập nhật nội dung tư vấn."


async def test_project_features_api_backfills_new_active_catalog_rows(
    client, db_session, clean_kb, clean_features
):
    proj = await _seed_project(db_session)
    doc = await _make_doc(db_session, "LG Display.", project_id=proj.id)

    active_count = (
        await db_session.execute(
            text("SELECT count(*) FROM worker_feature_catalog WHERE is_active = true")
        )
    ).scalar()
    contact_id = (
        await db_session.execute(
            text("SELECT id FROM worker_feature_catalog WHERE feature_key = 'contact_info'")
        )
    ).scalar()
    legacy_rows = (
        await db_session.execute(
            text(
                "SELECT id, feature_key, default_importance_score "
                "FROM worker_feature_catalog "
                "WHERE is_active = true AND feature_key <> 'contact_info' "
                "ORDER BY default_importance_score DESC, feature_key"
            )
        )
    ).all()
    for priority, row in enumerate(legacy_rows):
        await db_session.execute(
            text(
                "INSERT INTO job_feature_values "
                "(project_id, feature_id, value_text, value_json, strength_score, display_priority, "
                " is_highlight, is_missing, needs_clarification, source_document_id) "
                "VALUES (CAST(:pid AS uuid), CAST(:fid AS uuid), :value_text, '{}'::jsonb, "
                ":strength, :priority, false, false, false, CAST(:doc_id AS uuid))"
            ),
            {
                "pid": str(proj.id),
                "fid": str(row.id),
                "value_text": f"Legacy value for {row.feature_key}",
                "strength": row.default_importance_score,
                "priority": priority,
                "doc_id": str(doc.id),
            },
        )
    await db_session.commit()

    token = (
        await client.post(
            "/api/v1/auth/login",
            json={"email": RECRUITER_EMAIL, "password": PASSWORD},
        )
    ).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    features = await client.get(f"/api/v1/knowledge/projects/{proj.id}/features", headers=headers)
    assert features.status_code == 200
    body = features.json()
    assert body["total"] == active_count
    contact = next(item for item in body["data"] if item["feature_key"] == "contact_info")
    assert contact["feature_id"] == str(contact_id)
    assert contact["is_missing"] is True
    assert contact["value_text"] == ""
