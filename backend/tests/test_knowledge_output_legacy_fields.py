"""API knowledge output hides retired fields without changing stored history."""

from copy import deepcopy
from datetime import UTC, datetime
from types import SimpleNamespace
import uuid

from pydantic import ValidationError
import pytest

from app.schemas.knowledge import KnowledgeChunkOut, KnowledgeDocumentOut
from app.schemas.project_knowledge import CategoryRevisionOut


def _chunk(**changes):
    return {
        "id": uuid.uuid4(),
        "chunk_index": 0,
        "created_at": datetime.now(UTC),
        "content": 'Phúc lợi\njob_ids: ["old-operator"]\nvacancies: null\nname: "Cơm ca miễn phí"\n',
        "source_quote": 'jobs_ids:\n- "old-operator"\ndescription: "Một bữa trong mỗi ca"\n',
        "summary": '{"job_ids": ["old"], "employment_type": "temporary", "summary": "Cơm ca miễn phí"}',
        "questions": ["Có được bao cơm không?", 'job_ids: ["old"]\nCó được bao cơm không?'],
        "entities": {
            "stable_id": "food",
            "job_ids": ["old"],
            "vacancies": 100,
            "employment_type": None,
            "details": [{"jobs_ids": ["old"], "name": "Cơm ca miễn phí"}],
        },
        "citation_label": "Bảng thông tin tuyển dụng",
        "line_start": 4,
        "line_end": 8,
        **changes,
    }


def _document(**changes):
    return {
        "id": uuid.uuid4(),
        "file_name": "thong-tin.md",
        "source": "category_markdown",
        "status": "PUBLISHED",
        "created_at": datetime.now(UTC),
        "updated_at": datetime.now(UTC),
        "digest_summary": 'job_ids: ["old"]\nvacancies: null\nemployment_type: null\nCó cơm ca miễn phí.\n',
        "digest_meta": {
            "job_ids": ["old"],
            "vacancies": None,
            "employment_type": "temporary",
            "facts": [{"jobs_ids": ["old"], "description": "Cơm ca miễn phí"}],
            "notes": "Câu văn nhắc đến job_ids vẫn được giữ nguyên.",
            "project_training": {
                "status": "COMPLETED",
                "current": None,
                "completed": ["jobs", "benefits"],
                "error": None,
                "requires_cutover": True,
            },
        },
        **changes,
    }


def test_chunk_output_cleans_every_text_field_and_entities_without_mutating_input():
    row = _chunk()
    before = deepcopy(row)

    output = KnowledgeChunkOut.model_validate(row)

    assert row == before
    assert output.content == 'Phúc lợi\nname: "Cơm ca miễn phí"\n'
    assert output.source_quote == 'description: "Một bữa trong mỗi ca"\n'
    assert output.summary == '{"summary": "Cơm ca miễn phí"}'
    assert output.questions == ["Có được bao cơm không?", "Có được bao cơm không?"]
    assert output.entities == {
        "stable_id": "food",
        "details": [{"name": "Cơm ca miễn phí"}],
    }
    assert (output.citation_label, output.line_start, output.line_end) == (
        row["citation_label"],
        4,
        8,
    )
    assert output.id == row["id"]


def test_document_output_cleans_nested_metadata_and_keeps_original_progress_and_row():
    row = _document()
    stored = SimpleNamespace(**row)
    before = deepcopy(row)

    output = KnowledgeDocumentOut.model_validate(stored)

    assert vars(stored) == before
    assert output.digest_summary == "Có cơm ca miễn phí.\n"
    assert "job_ids" not in output.digest_meta
    assert "vacancies" not in output.digest_meta
    assert "employment_type" not in output.digest_meta
    assert output.digest_meta["facts"] == [{"description": "Cơm ca miễn phí"}]
    assert output.digest_meta["notes"] == row["digest_meta"]["notes"]
    assert output.digest_meta["project_training"] == row["digest_meta"]["project_training"]
    assert output.project_training.model_dump(mode="json", exclude_unset=True) == row["digest_meta"]["project_training"]
    assert output.project_training.planned == []
    assert output.project_training.covered_categories == []
    assert output.project_training.source_sections_completed is None
    assert (
        output.model_dump(mode="json", exclude_unset=True)["project_training"] == row["digest_meta"]["project_training"]
    )


def test_output_cleanup_does_not_remove_prose_examples_or_change_nullable_shape():
    prose = (
        "Câu văn nhắc đến job_ids và jobs_ids vẫn giữ nguyên.\n"
        '```json\n{"job_ids": ["example"]}\n```\n'
    )
    chunk = KnowledgeChunkOut.model_validate(
        _chunk(
            content=prose,
            source_quote=None,
            summary=None,
            questions=[prose],
            entities={"notes": "job_ids là một từ trong câu.", "stable_id": "original"},
        )
    )
    assert chunk.content == prose
    assert chunk.questions == [prose]
    assert chunk.source_quote is None
    assert chunk.summary is None
    assert chunk.entities == {"notes": "job_ids là một từ trong câu.", "stable_id": "original"}
    document = KnowledgeDocumentOut.model_validate(_document(digest_summary=None, digest_meta={}))
    assert document.digest_summary is None
    assert document.digest_meta == {}
    assert document.project_training is None


@pytest.mark.parametrize(
    "changes",
    [
        {"content": {"job_ids": ["old"]}},
        {"content": None},
        {"source_quote": {"job_ids": ["old"]}},
        {"summary": ["not", "text"]},
        {"questions": "not a list"},
        {"questions": [{"job_ids": ["old"]}]},
        {"entities": "not a mapping"},
    ],
)
def test_chunk_output_validates_original_field_types_before_cleanup(changes):
    with pytest.raises(ValidationError):
        KnowledgeChunkOut.model_validate(_chunk(**changes))


@pytest.mark.parametrize(
    "changes",
    [{"digest_summary": {"job_ids": ["old"]}}, {"digest_meta": "not a mapping"}],
)
def test_document_output_validates_original_field_types_before_cleanup(changes):
    with pytest.raises(ValidationError):
        KnowledgeDocumentOut.model_validate(_document(**changes))


def _revision(payload):
    return SimpleNamespace(
        id=uuid.uuid4(), category_id=uuid.uuid4(), revision_no=7, status="ACTIVE",
        source_filename="jobs.md", content_sha256="saved-checksum",
        normalized_payload=payload, created_at=datetime.now(UTC),
    )


def test_category_revision_receipt_omits_old_fields_without_mutating_historical_payload():
    payload = {
        "category": "jobs",
        "jobs": [{"id": "worker", "title": "Lắp ráp", "vacancies": 100, "employment_type": "temporary"}],
        "nested": {"job_ids": ["old"], "jobs_ids": [], "salary": 0, "transport": False},
    }
    stored = _revision(payload)
    original = deepcopy(payload)

    output = CategoryRevisionOut.model_validate(stored)

    assert stored.normalized_payload == original
    assert output.normalized_payload == {
        "category": "jobs", "jobs": [{"id": "worker", "title": "Lắp ráp"}],
        "nested": {"salary": 0, "transport": False},
    }
    assert output.content_sha256 == stored.content_sha256
    assert output.revision_no == stored.revision_no
    assert output.id == stored.id


@pytest.mark.parametrize("payload", [None, "not a mapping", ["not a mapping"]])
def test_category_revision_receipt_validates_original_payload_type(payload):
    with pytest.raises(ValidationError):
        CategoryRevisionOut.model_validate(_revision(payload))
