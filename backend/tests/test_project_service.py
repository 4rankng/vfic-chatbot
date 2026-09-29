import uuid
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from pydantic import ValidationError

from app.models.knowledge import KnowledgeBaseMode
from app.schemas.knowledge_bases import DirectContextFileUpsert
from app.schemas.projects import ProjectListResponse, ProjectOut, ProjectUpdate
from app.services.project import service as project_service
from app.services.project.repository import ProjectRepository
from app.services.project import ProjectService


class _FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def mappings(self):
        return self

    def all(self):
        return self._rows


class _FakeDb:
    def __init__(self, rows):
        self.rows = rows
        self.statement = None
        self.params = None

    async def get(self, _model, _project_id):
        return object()

    async def execute(self, statement, params):
        self.statement = statement
        self.params = params
        return _FakeResult(self.rows)


@pytest.mark.asyncio
async def test_list_faq_reads_source_anchor_from_chunk_metadata():
    project_id = uuid.uuid4()
    chunk_id = uuid.uuid4()
    db = _FakeDb(
        [
            {
                "id": chunk_id,
                "content": "FAQ: Lương bao nhiêu?\nTừ 10-13 triệu.",
                "questions": ["Lương bao nhiêu?"],
                "source_anchor": "FAQ §1",
                "file_name": "lgd-faq.md",
            }
        ]
    )

    response = await ProjectService(db).list_faq(project_id, limit=99)

    sql = str(db.statement)
    assert "kc.metadata ->> 'source_anchor' AS source_anchor" in sql
    assert "kc.source_anchor" not in sql
    assert db.params == {"pid": str(project_id), "limit": 50}
    assert response.total == 1
    assert response.data[0].id == chunk_id
    assert response.data[0].question == "Lương bao nhiêu?"
    assert response.data[0].answer == "Từ 10-13 triệu."
    assert response.data[0].source_anchor == "FAQ §1"


def test_project_schemas_no_longer_accept_or_serialize_default_persona_id() -> None:
    with pytest.raises(ValidationError):
        ProjectUpdate.model_validate({"default_persona_id": str(uuid.uuid4())})

    assert "default_persona_id" not in ProjectOut.model_json_schema()["properties"]


@pytest.mark.asyncio
async def test_replace_single_page_activates_ready_project_and_invalidates_catalog(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id = uuid.uuid4()
    knowledge_base_id = uuid.uuid4()
    actor = SimpleNamespace(id=uuid.uuid4())
    project = SimpleNamespace(
        id=project_id,
        is_active=False,
        index_card={"summary": "Rorze tuyển nhân viên vận hành máy CNC"},
    )
    knowledge_base = SimpleNamespace(
        id=knowledge_base_id,
        mode=KnowledgeBaseMode.DIRECT_CONTEXT,
    )
    service = ProjectService(SimpleNamespace())
    service._require_project = AsyncMock(return_value=project)
    service._require_project_mode = AsyncMock(return_value=knowledge_base)
    direct_file = SimpleNamespace(
        id=uuid.uuid4(),
        raw_text="Rorze tuyển nhân viên vận hành máy CNC.",
    )
    upsert_direct_file = AsyncMock(return_value=direct_file)
    audit = AsyncMock()
    bump = AsyncMock()
    monkeypatch.setattr(project_service, "record_audit", audit)
    monkeypatch.setattr(project_service, "bump_cache_version", bump)
    enqueue_jobs: list[tuple[uuid.UUID, uuid.UUID, str]] = []
    fake_jobs = SimpleNamespace(
        index_direct_context=lambda knowledge_base_id, project_id_arg, text_blob: enqueue_jobs.append(
            (knowledge_base_id, project_id_arg, text_blob)
        )
    )
    monkeypatch.setattr(
        "app.composition.project_knowledge_jobs.build_project_knowledge_direct_context_jobs",
        lambda: fake_jobs,
    )

    with patch(
        "app.services.project.service.KnowledgeBaseService"
    ) as knowledge_base_service:
        knowledge_base_service.return_value.upsert_direct_file = upsert_direct_file
        result = await service.replace_single_page(
            project_id,
            DirectContextFileUpsert(
                filename="rorze.md",
                text="Rorze tuyển nhân viên vận hành máy CNC.",
            ),
            actor,
        )

    assert result is direct_file
    assert project.is_active is True
    audit.assert_awaited_once_with(
        service.db,
        action="update_project",
        actor_id=actor.id,
        target_type="project",
        target_id=str(project_id),
        payload={"is_active": True, "reason": "single_page_ready"},
    )
    upsert_direct_file.assert_awaited_once()
    assert enqueue_jobs == [
        (
            knowledge_base_id,
            project_id,
            "Rorze tuyển nhân viên vận hành máy CNC.",
        )
    ]
    bump.assert_awaited_once_with(project_service.NS_PREAMBLE)


@pytest.mark.asyncio
async def test_knowledge_document_count_includes_direct_context_page() -> None:
    project_id = uuid.uuid4()
    db = _FakeDb([SimpleNamespace(project_id=project_id, file_count=1)])

    counts = await ProjectRepository(db).knowledge_document_counts([project_id])

    assert counts == {project_id: 1}
    assert "knowledge_base_direct_files" in str(db.statement)


class _IngestDb:
    """Fake session answering only the two batched ingest queries, by source table."""

    def __init__(
        self,
        revisions: list[tuple[uuid.UUID, str]] | None = None,
        documents: list[tuple[uuid.UUID, str]] | None = None,
    ) -> None:
        self.revision_rows = [
            SimpleNamespace(project_id=project_id, status=status)
            for project_id, status in (revisions or [])
        ]
        self.document_rows = [
            SimpleNamespace(project_id=project_id, status=status)
            for project_id, status in (documents or [])
        ]
        self.calls: list[tuple[str, dict]] = []

    async def execute(self, statement, params):
        sql = str(statement)
        self.calls.append((sql, params))
        if "knowledge_category_revisions" in sql:
            return _FakeResult(self.revision_rows)
        if "knowledge_documents" in sql:
            return _FakeResult(self.document_rows)
        raise AssertionError(f"unexpected statement: {sql}")


def _project_row(project_id: uuid.UUID) -> SimpleNamespace:
    return SimpleNamespace(
        id=project_id,
        slug="kho-tri-thuc",
        name="Kho tri thuc",
        aliases=[],
        is_active=True,
        knowledge_mode=None,
        summary=None,
        index_card={},
        discovery_revision=0,
        knowledge_base_id=None,
        created_at=datetime(2026, 9, 1),
        updated_at=datetime(2026, 9, 1),
    )


def _stub_projection_dependencies(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stub the readiness/doc-count aggregates so only ingest queries hit the fake db."""
    feature_repo = SimpleNamespace(
        readiness_by_project=AsyncMock(return_value={}),
        active_catalog_size=AsyncMock(return_value=0),
    )
    monkeypatch.setattr(project_service, "JobFeatureValueRepo", lambda *_args: feature_repo)
    project_repo = SimpleNamespace(knowledge_document_counts=AsyncMock(return_value={}))
    monkeypatch.setattr(project_service, "ProjectRepository", lambda *_args: project_repo)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("revision_statuses", "document_statuses", "expected"),
    [
        ([], [], None),
        (["STAGED"], [], "ingesting"),
        (["PROCESSING"], [], "ingesting"),
        (["ACTIVE"], [], "ready"),
        (["FAILED"], [], "error"),
        (["ARCHIVED", "CLEARED"], [], None),
        (["ACTIVE", "FAILED"], [], "error"),
        (["FAILED", "STAGED"], [], "ingesting"),
        (["ACTIVE", "FAILED", "PROCESSING"], [], "ingesting"),
        ([], ["UPLOADED"], "ingesting"),
        ([], ["PROCESSING"], "ingesting"),
        ([], ["PUBLISHED"], "ready"),
        ([], ["FAILED"], "error"),
        ([], ["ARCHIVED"], None),
        (["ACTIVE"], ["FAILED"], "error"),
        (["FAILED"], ["UPLOADED"], "ingesting"),
        (["CLEARED"], ["PUBLISHED"], "ready"),
    ],
)
async def test_ingest_state_aggregates_and_serializes_on_list_and_get_paths(
    monkeypatch: pytest.MonkeyPatch,
    revision_statuses: list[str],
    document_statuses: list[str],
    expected: str | None,
) -> None:
    project_id = uuid.uuid4()
    db = _IngestDb(
        revisions=[(project_id, status) for status in revision_statuses],
        documents=[(project_id, status) for status in document_statuses],
    )
    _stub_projection_dependencies(monkeypatch)
    row = _project_row(project_id)
    service = ProjectService(db)
    service.list = AsyncMock(return_value=([row], 1))
    service._require_project = AsyncMock(return_value=row)

    data, total = await service.list_with_readiness()
    out = await service.get_with_readiness(project_id)

    listed = ProjectListResponse(data=data, total=total)
    assert listed.model_dump()["data"][0]["ingest_state"] == expected
    assert out.model_dump()["ingest_state"] == expected
    assert "ingest_state" in ProjectOut.model_json_schema()["properties"]


@pytest.mark.asyncio
async def test_ingest_state_fetch_is_batched_per_source(monkeypatch: pytest.MonkeyPatch) -> None:
    first, second = uuid.uuid4(), uuid.uuid4()
    db = _IngestDb(
        revisions=[(first, "STAGED")],
        documents=[(second, "FAILED")],
    )
    _stub_projection_dependencies(monkeypatch)
    service = ProjectService(db)
    service.list = AsyncMock(return_value=([_project_row(first), _project_row(second)], 2))

    data, _total = await service.list_with_readiness()

    assert len(db.calls) == 2  # one query per source, not one per project
    assert all(params == {"ids": [str(first), str(second)]} for _sql, params in db.calls)
    revision_sql = next(sql for sql, _params in db.calls if "knowledge_category_revisions" in sql)
    assert "MAX(r.revision_no)" in revision_sql  # only each category's latest revision counts
    assert {row.id: row.ingest_state for row in data} == {first: "ingesting", second: "error"}
