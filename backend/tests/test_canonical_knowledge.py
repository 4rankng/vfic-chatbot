"""VFIC Knowledge Markdown v1 parser and ingest contract tests."""
from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest
from sqlalchemy import text

from app.models.knowledge import KnowledgeDocument, KnowledgeStatus
from app.services.knowledge.canonical import (
    CanonicalValidationError,
    checksum_text,
    load_template,
    parse_canonical_markdown,
    repair_canonical_markdown,
)
from app.services.knowledge.pipeline import KnowledgePipeline
from app.services.knowledge_service import KnowledgeService
from app.graph.tools import search_knowledge
from tests.conftest import ADMIN_EMAIL, PASSWORD

VEC = [0.01] * 3072
FIXTURE = Path(__file__).resolve().parent / "fixtures" / "canonical" / "golden_vfic_knowledge_v1.json"


class _FakeEmbedder:
    async def embed(self, _t):
        return list(VEC)

    async def batch(self, texts):
        return [list(VEC) for _ in texts]

    __call__ = embed


class _CollapsingBatchEmbedder:
    async def embed(self, _t):
        return list(VEC)

    async def batch(self, texts):
        return [list(VEC)] if texts else []

    __call__ = embed


async def _admin_token(client) -> str:
    response = await client.post(
        "/api/v1/auth/login", json={"email": ADMIN_EMAIL, "password": PASSWORD}
    )
    return response.json()["access_token"]


async def _noop_llm(_system, _user):
    return json.dumps({"document_summary": "", "units": []})


def _normalized(parsed) -> dict:
    route = parsed.bus_timetable.routes[0]
    return {
        "doc_id": parsed.metadata["doc_id"],
        "schema_version": parsed.metadata["schema_version"],
        "chunk_count": len(parsed.chunks),
        "chunk_labels": [chunk.citation.label for chunk in parsed.chunks],
        "route_count": len(parsed.bus_timetable.routes),
        "routes": [
            {
                "route_name": route.route_name,
                "route_group_key": route.route_group_key,
                "shift": route.shift,
                "direction": route.direction,
                "stop_count": len(route.stops),
                "first_stop": route.stops[0].stop_name,
                "first_time": route.stops[0].scheduled_time.strftime("%H:%M"),
            }
        ],
        "service_day_count": len(parsed.bus_timetable.service_days),
        "effective_from": parsed.metadata["effective_from"],
        "effective_to": parsed.metadata["effective_to"],
    }


def test_canonical_template_matches_golden_fixture():
    parsed = parse_canonical_markdown(load_template())
    assert _normalized(parsed) == json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_canonical_parser_tolerates_crlf_and_bom():
    """An admin editing the downloaded template on Windows saves CRLF (and may add a
    UTF-8 BOM); the parser must still accept it and produce the golden shape."""
    crlf_bom = "﻿" + load_template().replace("\n", "\r\n")
    parsed = parse_canonical_markdown(crlf_bom)
    assert _normalized(parsed) == json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_canonical_parser_rejects_missing_frontmatter():
    with pytest.raises(CanonicalValidationError) as exc:
        parse_canonical_markdown("# Missing frontmatter")
    assert "frontmatter" in str(exc.value)


def test_canonical_parser_rejects_list_item_under_scalar_key():
    bad = load_template().replace(
        'company_name: "LG Display"\nproject_slug:',
        'company_name: "LG Display"\n  - illegal\nproject_slug:',
    )
    with pytest.raises(CanonicalValidationError) as exc:
        parse_canonical_markdown(bad)
    assert any("list item cannot be added to scalar key" in err for err in exc.value.errors)


def test_canonical_parser_rejects_invalid_bus_time():
    bad = load_template().replace("| 1 | TD Plaza | TD Plaza | 06:15 |", "| 1 | TD Plaza | TD Plaza | 6:15 |")
    with pytest.raises(CanonicalValidationError) as exc:
        parse_canonical_markdown(bad)
    assert any("scheduled_time must use HH:MM" in err for err in exc.value.errors)


def test_canonical_parser_rejects_unknown_feature_key():
    bad = load_template().replace(
        "### Feature: take_home_income",
        "### Feature: career_growth",
        1,
    )
    with pytest.raises(CanonicalValidationError) as exc:
        parse_canonical_markdown(bad)
    assert any("unknown or inactive feature key 'career_growth'" in err for err in exc.value.errors)


def test_canonical_parser_rejects_missing_active_feature_key():
    bad = load_template().replace("### Feature: daily_cost_benefits", "### Removed: daily_cost_benefits", 1)
    with pytest.raises(CanonicalValidationError) as exc:
        parse_canonical_markdown(bad)
    assert any("missing active feature keys daily_cost_benefits" in err for err in exc.value.errors)


def test_canonical_repair_fixes_known_bus_route_formatting_artifacts():
    bad = load_template() + """

### Bus Route: Admin weekday generic return

route_id: admin_weekday_generic_return
route_group: All admin routes with return_admin active
route_name: Lượt về hành chính ngày thường
route_no: "RETURN_ADMIN_WEEKDAY"
route_variant: "generic"
shift: admin
direction: return
area: All listed areas
mode: generic_return
notes: Check each route_group weekly `return_admin` status before confirming availability.

service_days:
- mon_thu: check route-specific return_admin status; departure_time=18:30
- fri: check route-specific return_admin status; departure_time=17:30
- sat: use admin_weekend_inner_city_return only if status return_admin=M
- sun: use admin_weekend_inner_city_return only if status return_admin=M

| stop_order | stop_name | aliases | scheduled_time | notes |
|---|---|---|---|---|
| 1 | Bãi đỗ xe LGDVH | LGD | 18:30 mon_thu; 17:30 fri | Departure point |
"""
    with pytest.raises(CanonicalValidationError) as exc:
        parse_canonical_markdown(bad)
    assert any("malformed service flag" in err for err in exc.value.errors)
    assert any("scheduled_time must use HH:MM" in err for err in exc.value.errors)

    repaired = repair_canonical_markdown(bad)
    assert repaired.changed
    assert {fix["code"] for fix in repaired.repairs} == {
        "drop_prose_service_days",
        "move_non_scalar_scheduled_time_to_notes",
    }
    parsed = parse_canonical_markdown(repaired.text)
    repaired_route = parsed.bus_timetable.routes[-1]
    assert repaired_route.route_name == "Lượt về hành chính ngày thường"
    assert repaired_route.stops[0].scheduled_time is None
    assert "Scheduled time note: 18:30 mon_thu; 17:30 fri." in repaired.text


def test_canonical_parser_accepts_status_only_bus_weekly_rows_without_route():
    status_only = load_template() + """

### Bus Route: Nam Am - B16 weekly status only

route_id: nam_am_b16_weekly_status_only
route_group: Nam Am - B16
route_name: Nam Am - B16
route_no: "status_only"
route_variant: "status_only"
shift: weekly_status_only
direction: unknown
area: Ngoại thành Hải Phòng
mode: status_only
notes: This route appears in the weekly operation table only.

service_days:
- mon_thu: outbound_admin_and_day=A, return_night=A, return_admin=A, outbound_night=A, return_day=A
- fri: outbound_admin_and_day=A, return_night=A, return_admin=A, outbound_night=A, return_day=A
- sat: outbound_admin_and_day=A, return_night=A, return_admin=X, outbound_night=A, return_day=A
- sun: outbound_admin_and_day=A, return_night=A, return_admin=X, outbound_night=A, return_day=A
"""
    parsed = parse_canonical_markdown(status_only)
    assert len(parsed.bus_timetable.routes) == 1
    assert len(parsed.bus_timetable.service_days) == 40
    assert any(day.route_group_name == "Nam Am - B16" for day in parsed.bus_timetable.service_days)


@pytest.mark.asyncio
async def test_template_endpoint_requires_admin_and_returns_markdown(client):
    token = await _admin_token(client)
    response = await client.get(
        "/api/v1/knowledge/format/template",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    assert "vfic-knowledge-v1" in response.text
    assert response.headers["content-type"].startswith("text/markdown")


@pytest.mark.asyncio
async def test_upload_file_rejects_noncanonical_without_enqueue(client, monkeypatch, clean_kb):
    enqueued: list[str] = []
    monkeypatch.setattr(
        "app.api.knowledge.enqueue_ingest", lambda doc_id: enqueued.append(str(doc_id))
    )
    token = await _admin_token(client)
    response = await client.post(
        "/api/v1/knowledge/documents/upload-file",
        files={"file": ("bad.txt", b"raw random text", "text/plain")},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 422
    assert enqueued == []
    assert response.json()["detail"]["errors"]


@pytest.mark.asyncio
async def test_upload_file_accepts_canonical_and_stores_metadata(client, db_session, monkeypatch, clean_kb):
    enqueued: list[str] = []
    monkeypatch.setattr(
        "app.api.knowledge.enqueue_ingest", lambda doc_id: enqueued.append(str(doc_id))
    )
    token = await _admin_token(client)
    payload = load_template().encode("utf-8")
    response = await client.post(
        "/api/v1/knowledge/documents/upload-file",
        files={"file": ("canonical.md", payload, "text/markdown")},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["is_canonical"] is True
    assert enqueued == [body["id"]]
    doc = await db_session.get(KnowledgeDocument, uuid.UUID(body["id"]))
    assert doc is not None
    assert doc.metadata_["schema_version"] == "vfic-knowledge-v1"
    assert doc.metadata_["canonical"]["validation"]["bus_route_count"] == 1


@pytest.mark.asyncio
async def test_upload_file_auto_repairs_canonical_bus_formatting(client, db_session, monkeypatch, clean_kb):
    enqueued: list[str] = []
    monkeypatch.setattr(
        "app.api.knowledge.enqueue_ingest", lambda doc_id: enqueued.append(str(doc_id))
    )
    token = await _admin_token(client)
    bad = load_template() + """

### Bus Route: Day shift generic return

route_id: day_shift_generic_return
route_group: All day routes
route_name: Lượt về ca ngày
route_no: "RETURN_DAY"
route_variant: "generic"
shift: day
direction: return
area: All listed areas
mode: generic_return
notes: Check each route_group weekly `return_day` status before confirming availability.

service_days:
- mon_thu: check route-specific return_day status
- fri: check route-specific return_day status
- sat: check route-specific return_day status
- sun: check route-specific return_day status

| stop_order | stop_name | aliases | scheduled_time | notes |
|---|---|---|---|---|
| 1 | Bãi đỗ xe LGDVH | LGD | 20:35 | Departure point |
"""
    response = await client.post(
        "/api/v1/knowledge/documents/upload-file",
        files={"file": ("canonical-repair.md", bad.encode("utf-8"), "text/markdown")},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["is_canonical"] is True
    assert enqueued == [body["id"]]
    doc = await db_session.get(KnowledgeDocument, uuid.UUID(body["id"]))
    assert doc is not None
    assert doc.raw_text != bad
    assert doc.metadata_["checksum"] == checksum_text(doc.raw_text)
    repair = doc.metadata_["canonical"]["repair"]
    assert repair["applied"] is True
    assert repair["original_checksum"] == checksum_text(bad)
    assert repair["fixes"][0]["code"] == "drop_prose_service_days"


@pytest.mark.asyncio
async def test_canonical_pipeline_publishes_chunks_and_bus_without_filename_dependency(db_session, clean_kb):
    await db_session.execute(text("DELETE FROM knowledge_sources WHERE source_name = 'not-lgdisplay.md'"))
    await db_session.commit()
    doc = await KnowledgeService(db_session).upload_bytes(
        "not-lgdisplay.md",
        "text/markdown",
        load_template().encode("utf-8"),
        require_canonical=True,
    )

    await KnowledgePipeline(db_session, _FakeEmbedder(), _noop_llm).run(doc)
    await db_session.refresh(doc)

    assert doc.status == KnowledgeStatus.PUBLISHED
    chunks = (
        await db_session.execute(
            text("SELECT metadata FROM knowledge_chunks WHERE document_id = :did ORDER BY chunk_index"),
            {"did": str(doc.id)},
        )
    ).scalars().all()
    assert len(chunks) == 16
    assert chunks[0]["citation"]["label"] == "LG Display Worker Guide, Company Overview"
    assert chunks[1]["chunk_metadata"]["content_type"] == "company_knowledge"
    assert chunks[1]["chunk_metadata"]["tags"][-1] == "take_home_income"
    route_count = (
        await db_session.execute(
            text(
                "SELECT count(*) FROM bus_routes br "
                "JOIN knowledge_sources ks ON ks.id = br.knowledge_source_id "
                "WHERE ks.source_name = 'not-lgdisplay.md'"
            )
        )
    ).scalar()
    assert route_count == 1


@pytest.mark.asyncio
async def test_canonical_pipeline_skips_llm_enrichment_even_with_project(db_session, clean_kb):
    project_id = (
        await db_session.execute(
            text(
                "INSERT INTO projects(slug,name,is_active) "
                "VALUES (:slug,'Canonical Fast Path',true) RETURNING id"
            ),
            {"slug": f"canonical-fast-{uuid.uuid4().hex[:8]}"},
        )
    ).scalar_one()
    await db_session.commit()
    doc = await KnowledgeService(db_session).upload_bytes(
        "canonical-fast.md",
        "text/markdown",
        load_template().encode("utf-8"),
        project_id=project_id,
        require_canonical=True,
    )
    llm_calls: list[str] = []

    async def exploding_llm(system, user):
        llm_calls.append(system)
        raise AssertionError("canonical ingest should not call LLM")

    await KnowledgePipeline(db_session, _FakeEmbedder(), exploding_llm).run(doc)
    await db_session.refresh(doc)

    assert doc.status == KnowledgeStatus.PUBLISHED
    assert doc.stage == "PUBLISHED"
    assert doc.digest_meta["unit_count"] == 16
    assert llm_calls == []


@pytest.mark.asyncio
async def test_canonical_pipeline_stores_all_units_when_batch_embedder_collapses(db_session, clean_kb):
    doc = await KnowledgeService(db_session).upload_bytes(
        "canonical-collapsed-batch.md",
        "text/markdown",
        load_template().encode("utf-8"),
        require_canonical=True,
    )

    await KnowledgePipeline(db_session, _CollapsingBatchEmbedder(), _noop_llm).run(doc)
    await db_session.refresh(doc)

    chunk_count = (
        await db_session.execute(
            text("SELECT count(*) FROM knowledge_chunks WHERE document_id = :did"),
            {"did": str(doc.id)},
        )
    ).scalar_one()
    assert doc.status == KnowledgeStatus.PUBLISHED
    assert doc.digest_meta["unit_count"] == 16
    assert chunk_count == doc.digest_meta["unit_count"]


@pytest.mark.asyncio
async def test_canonical_pipeline_checksum_mismatch_marks_failed_in_worker_path(db_session, clean_kb):
    doc = await KnowledgeService(db_session).upload_bytes(
        "canonical.md",
        "text/markdown",
        load_template().encode("utf-8"),
        require_canonical=True,
    )
    doc.raw_text = doc.raw_text + "\nchanged"
    await db_session.commit()
    with pytest.raises(ValueError):
        await KnowledgePipeline(db_session, _FakeEmbedder(), _noop_llm).run(doc)


@pytest.mark.asyncio
async def test_canonical_pipeline_requires_bus_timetable_persistence(db_session, clean_kb, monkeypatch):
    doc = await KnowledgeService(db_session).upload_bytes(
        "canonical.md",
        "text/markdown",
        load_template().encode("utf-8"),
        require_canonical=True,
    )

    async def fail_bus_upsert(*_args, **_kwargs):
        raise RuntimeError("bus upsert unavailable")

    monkeypatch.setattr(KnowledgePipeline, "_persist_canonical_bus_timetable", fail_bus_upsert)
    with pytest.raises(RuntimeError, match="bus upsert unavailable"):
        await KnowledgePipeline(db_session, _FakeEmbedder(), _noop_llm).run(doc)


@pytest.mark.asyncio
async def test_search_knowledge_filters_canonical_effective_dates_and_keeps_legacy(db_session, clean_kb):
    slug = f"date-scope-{uuid.uuid4().hex[:8]}"
    project_id = (
        await db_session.execute(
            text(
                "INSERT INTO projects(slug,name,is_active) "
                "VALUES (:slug,'Date Scope',true) RETURNING id"
            ),
            {"slug": slug},
        )
    ).scalar_one()
    vec = "[" + ",".join(["0.01000000"] * 3072) + "]"

    async def _insert_doc(file_name: str, content: str, metadata: dict) -> None:
        doc_id = (
            await db_session.execute(
                text(
                    "INSERT INTO knowledge_documents(file_name,source,status,raw_text,metadata,project_id) "
                    "VALUES (:fn,'upload','PUBLISHED',:raw,'{}'::jsonb,:pid) RETURNING id"
                ),
                {"fn": file_name, "raw": content, "pid": project_id},
            )
        ).scalar_one()
        await db_session.execute(
            text(
                "INSERT INTO knowledge_chunks(document_id,chunk_index,content,embedding,metadata,project_id) "
                "VALUES (:did,0,:content,CAST(:emb AS vector),CAST(:meta AS jsonb),:pid)"
            ),
            {
                "did": doc_id,
                "content": content,
                "emb": vec,
                "meta": json.dumps(metadata),
                "pid": project_id,
            },
        )

    await _insert_doc(
        "current.md",
        "CURRENT canonical salary policy",
        {
            "document_metadata": {
                "schema_version": "vfic-knowledge-v1",
                "effective_from": "2020-01-01",
                "effective_to": None,
                "title": "Current",
            },
            "citation": {"label": "Current, Policy", "source_anchor": "Policy"},
        },
    )
    await _insert_doc(
        "expired.md",
        "EXPIRED canonical salary policy",
        {
            "document_metadata": {
                "schema_version": "vfic-knowledge-v1",
                "effective_from": "2020-01-01",
                "effective_to": "2020-12-31",
                "title": "Expired",
            },
            "citation": {"label": "Expired, Policy", "source_anchor": "Policy"},
        },
    )
    await _insert_doc("legacy.txt", "LEGACY null-date policy", {})
    await db_session.commit()

    output = await search_knowledge(db_session, _FakeEmbedder(), "salary policy", project_slug=slug)
    assert "CURRENT canonical" in output
    assert "LEGACY null-date" in output
    assert "EXPIRED canonical" not in output
    assert "Nguồn: Current, Policy" in output
