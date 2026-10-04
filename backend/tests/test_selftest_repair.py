"""LLM self-test repair: offending labels get rewritten, unusable output fails."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
import uuid
from unittest.mock import AsyncMock

import pytest

from app.models.knowledge import (
    KnowledgeCategory,
    KnowledgeCategoryRevision,
    KnowledgeCategoryRevisionStatus,
)
from app.services.knowledge.category_batch import (
    SELFTEST_REPAIR_MAX_ATTEMPTS,
    TrainingCategoryBatch,
    _parse_repair_value,
    repair_selftest_records,
)
from app.services.knowledge.category_contracts import category_checksum
from app.services.knowledge.category_markdown import parse_category_markdown
from app.services.knowledge.category_projections import render_category_units
from app.services.knowledge.category_service import CategoryActivationError
from app.services.knowledge.chunk_repository import KnowledgeChunkRepo

BAD_LABEL = "BHXH, BHYT, BHTN"
FAILURE = (
    f'"{BAD_LABEL}" would not retrieve its own record '
    "(own-record similarity 0.42 < 0.45)"
)
NEW_LABEL = "Bảo hiểm xã hội, y tế, thất nghiệp"

INSURANCE_MD = (
    '---\nschema_version: "1.0"\ncategory: insurance\n---\n\n## insurance\n\n'
    "### record: bao-hiem\n"
    f'name: "{BAD_LABEL}"\n'
    'eligibility: "Lao động thời vụ"\n'
    'starts_after: "từ tháng làm việc thứ 3 nếu có nhu cầu"\n'
    'notes: "Công nhân được đóng BHXH, BHYT, BHTN từ tháng làm việc thứ 3 '
    'nếu có nhu cầu."\n'
)


def _document():
    return parse_category_markdown("insurance", INSURANCE_MD)


def _units(document):
    return render_category_units(document)


async def test_repairs_offending_label_via_llm():
    document = _document()
    calls = []

    async def llm(system, user):
        calls.append((system, user))
        return json.dumps({"name": NEW_LABEL}, ensure_ascii=False)

    changed = await repair_selftest_records(document, _units(document), [FAILURE], llm)
    assert changed
    assert document.insurance[0].name == NEW_LABEL
    system, user = calls[0]
    assert "không bịa" in system
    payload = json.loads(user)
    assert payload["field_to_rewrite"] == "name"
    assert payload["record"]["name"] == BAD_LABEL


async def test_unusable_llm_output_leaves_record_and_fails_false():
    document = _document()

    async def llm(_system, _user):
        return "Xin lỗi, tôi không thể trả lời bằng JSON."

    changed = await repair_selftest_records(document, _units(document), [FAILURE], llm)
    assert not changed
    assert document.insurance[0].name == BAD_LABEL


async def test_records_without_query_field_are_not_touched():
    document = parse_category_markdown(
        "insurance",
        INSURANCE_MD
        + '\n\n### record: kham-suc-khoe\n'
        + 'name: "Khám sức khỏe khi đóng BHXH"\n'
        + 'notes: "Công nhân tự túc khám sức khỏe."\n',
    )
    seen = []

    async def llm(system, user):
        seen.append(json.loads(user))
        return json.dumps({"name": NEW_LABEL}, ensure_ascii=False)

    changed = await repair_selftest_records(document, _units(document), [FAILURE], llm)
    assert changed
    assert len(seen) == 1  # only the offending record was sent
    assert seen[0]["record"]["name"] == BAD_LABEL
    assert document.insurance[1].name == "Khám sức khỏe khi đóng BHXH"


def test_parse_repair_value_shapes():
    good = json.dumps({"name": "  Bảo hiểm xã hội  "}, ensure_ascii=False)
    assert _parse_repair_value(good, "name") == "Bảo hiểm xã hội"
    assert _parse_repair_value('tiền tố {"name":"BHXH đầy đủ"} hậu tố', "name") == "BHXH đầy đủ"
    assert _parse_repair_value("không có json", "name") is None
    assert _parse_repair_value(json.dumps({"other": "x"}), "name") is None
    assert _parse_repair_value(json.dumps({"name": "   "}), "name") is None


class _Embedder:
    """Scripted provider: one response list per batch() call."""

    def __init__(self, responses):
        self.responses = list(responses)

    async def batch(self, texts):
        return self.responses.pop(0)


class _PrepareDb:
    def __init__(self, revision, category):
        self.revision = revision
        self.category = category
        self.commits = 0

    async def scalar(self, statement):
        # The revision reload selects the entity itself; every other scalar
        # in the prepare flow is the MAX(revision_no) query.
        if statement.column_descriptions[0]["expr"] is KnowledgeCategoryRevision:
            return self.revision
        return self.revision.revision_no

    async def get(self, model, _id):
        return self.category if model is KnowledgeCategory else None

    def add(self, _obj):
        return None

    async def flush(self):
        return None

    async def commit(self):
        self.commits += 1

    async def rollback(self):
        return None


FUTURE_ISO = (datetime.now(UTC) + timedelta(minutes=30)).isoformat()


def _prepare_fixtures(llm):
    document = _document()
    doc = SimpleNamespace(
        id=uuid.uuid4(),
        project_id=uuid.uuid4(),
        metadata_={"project_training": {"lease_expires_at": FUTURE_ISO}},
    )
    revision = SimpleNamespace(
        id=uuid.uuid4(),
        status=KnowledgeCategoryRevisionStatus.STAGED,
        attempt_count=0,
        quality_result={"project_training_document_id": str(doc.id)},
        processing_token=None,
        processing_started_at=None,
        lease_expires_at=None,
        error_message=None,
        failure_code=None,
        source_markdown=INSURANCE_MD,
        content_sha256=category_checksum(document),
        normalized_payload=document.model_dump(mode="json"),
        revision_no=4,
        source_filename="insurance.md",
        category_id=uuid.uuid4(),
    )
    category = SimpleNamespace(
        id=revision.category_id,
        category_key="insurance",
        project_id=doc.project_id,
        active_revision_id=None,
    )
    db = _PrepareDb(revision, category)
    batch = TrainingCategoryBatch(db, SimpleNamespace(_enforce_retrieval_selftest=True), doc.id)
    return batch, doc, revision, llm


async def test_prepare_repairs_label_and_persists_repaired_content(monkeypatch):
    calls = []

    async def llm(system, user):
        calls.append((system, user))
        return json.dumps({"name": NEW_LABEL}, ensure_ascii=False)

    batch, doc, revision, llm = _prepare_fixtures(llm)

    async def no_snapshot(_doc):
        return None

    monkeypatch.setattr(batch, "_check_snapshot", no_snapshot)
    monkeypatch.setattr(KnowledgeChunkRepo, "insert_category_revision", AsyncMock(return_value=1))
    import app.services.knowledge.category_batch as batch_module

    monkeypatch.setattr(batch_module, "category_projection_allowed", AsyncMock(return_value=False))
    monkeypatch.setattr(batch_module, "record_audit", AsyncMock())

    zero = [0.0, 1.0]
    one = [1.0, 0.0]
    # unit embed (orthogonal to the label) → label query (cosine 0.0, fails)
    # → repaired unit embed → label query (cosine 1.0, passes).
    embedder = _Embedder([[zero], [one], [one], [one]])

    await batch.prepare(doc, revision, embedder, llm_json=llm)

    assert len(calls) == 1  # one repair round was enough
    assert NEW_LABEL in revision.source_markdown
    persisted = parse_category_markdown("insurance", revision.source_markdown)
    assert revision.content_sha256 == category_checksum(persisted)
    assert revision.normalized_payload["insurance"][0]["name"] == NEW_LABEL
    assert revision.quality_result["selftest_repair_attempts"] == 1
    assert revision.quality_result.get("prepared_document_id")


async def test_prepare_stops_when_llm_cannot_rewrite(monkeypatch):
    attempts = []

    async def llm(system, user):
        attempts.append(user)
        return "không phải JSON"

    batch, doc, revision, llm = _prepare_fixtures(llm)

    async def no_snapshot(_doc):
        return None

    monkeypatch.setattr(batch, "_check_snapshot", no_snapshot)

    zero, one = [0.0, 1.0], [1.0, 0.0]
    embedder = _Embedder([[zero], [one]])

    with pytest.raises(CategoryActivationError) as excinfo:
        await batch.prepare(doc, revision, embedder, llm_json=llm)
    assert excinfo.value.args[0] == "category_retrieval_selftest_failed"
    assert len(attempts) == 1  # an unusable round ends the loop at once
    assert revision.source_markdown == INSURANCE_MD  # nothing was persisted


async def test_prepare_bounded_attempts_when_repairs_never_pass(monkeypatch):
    attempts = []

    async def llm(system, user):
        attempts.append(user)
        return json.dumps({"name": f"Nhãn thử lại {len(attempts)}"}, ensure_ascii=False)

    batch, doc, revision, llm = _prepare_fixtures(llm)

    async def no_snapshot(_doc):
        return None

    monkeypatch.setattr(batch, "_check_snapshot", no_snapshot)

    zero, one = [0.0, 1.0], [1.0, 0.0]
    # Every round embeds orthogonal vectors, so the gate keeps failing no
    # matter what the LLM writes.
    embedder = _Embedder([[zero], [one]] * (SELFTEST_REPAIR_MAX_ATTEMPTS + 1))

    with pytest.raises(CategoryActivationError) as excinfo:
        await batch.prepare(doc, revision, embedder, llm_json=llm)
    assert excinfo.value.args[0] == "category_retrieval_selftest_failed"
    assert len(attempts) == SELFTEST_REPAIR_MAX_ATTEMPTS
    assert revision.source_markdown == INSURANCE_MD  # nothing was persisted
