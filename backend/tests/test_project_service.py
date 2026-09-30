import uuid
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from pydantic import ValidationError

from app.models.knowledge import KnowledgeBaseMode
from app.schemas.knowledge_bases import DirectContextFileUpsert
from app.schemas.projects import ProjectCreate, ProjectListResponse, ProjectOut, ProjectUpdate
from app.services.project import service as project_service
from app.services.project.repository import ProjectRepository
from app.services.project import ProjectService
from app.shared.domain.errors import ConflictError


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
        revisions: list[tuple[uuid.UUID, str, datetime | None]] | None = None,
        documents: list[tuple[uuid.UUID, str, datetime | None]] | None = None,
    ) -> None:
        self.revision_rows = [
            SimpleNamespace(project_id=project_id, status=status, freshest_at=freshest_at)
            for project_id, status, freshest_at in (revisions or [])
        ]
        self.document_rows = [
            SimpleNamespace(project_id=project_id, status=status, freshest_at=freshest_at)
            for project_id, status, freshest_at in (documents or [])
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


def _at(day: int) -> datetime:
    """A deterministic freshness stamp for ingest artifacts (Sept 2026)."""
    return datetime(2026, 9, day)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("revision_artifacts", "document_artifacts", "expected"),
    [
        # Nothing counting at all — the badge is absent (None).
        ([], [], None),
        ([("ARCHIVED", 2), ("CLEARED", 3)], [], None),
        ([], [("ARCHIVED", 3)], None),
        # Any in-flight artifact wins, wherever it sits in time.
        ([("STAGED", 2)], [], "ingesting"),
        ([("PROCESSING", 2)], [], "ingesting"),
        ([("FAILED", 1), ("STAGED", 2)], [], "ingesting"),
        ([("ACTIVE", 1), ("FAILED", 1), ("PROCESSING", 2)], [], "ingesting"),
        ([], [("UPLOADED", 2)], "ingesting"),
        ([], [("PROCESSING", 2)], "ingesting"),
        ([], [("FAILED", 1), ("PROCESSING", 2)], "ingesting"),
        ([("FAILED", 2)], [("UPLOADED", 1)], "ingesting"),
        # A single counting artifact decides.
        ([("ACTIVE", 2)], [], "ready"),
        ([("FAILED", 2)], [], "error"),
        ([], [("PUBLISHED", 2)], "ready"),
        ([], [("FAILED", 2)], "error"),
        ([("CLEARED", 1)], [("PUBLISHED", 2)], "ready"),
        # The LG case: a failure superseded by later successes is history.
        ([], [("FAILED", 1), ("PUBLISHED", 2)], "ready"),
        ([("FAILED", 1)], [("PUBLISHED", 2)], "ready"),
        # Newest artifact FAILED with nothing newer → error, from either source.
        ([("ACTIVE", 1)], [("FAILED", 2)], "error"),
        ([("FAILED", 2)], [("PUBLISHED", 1)], "error"),
        # Mixed same-freshness newest rows: any failure among them → error.
        ([("ACTIVE", 2), ("FAILED", 2)], [], "error"),
        ([("ACTIVE", 2)], [("FAILED", 2)], "error"),
    ],
)
async def test_ingest_state_aggregates_and_serializes_on_list_and_get_paths(
    monkeypatch: pytest.MonkeyPatch,
    revision_artifacts: list[tuple[str, int]],
    document_artifacts: list[tuple[str, int]],
    expected: str | None,
) -> None:
    project_id = uuid.uuid4()
    db = _IngestDb(
        revisions=[(project_id, status, _at(day)) for status, day in revision_artifacts],
        documents=[(project_id, status, _at(day)) for status, day in document_artifacts],
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
        revisions=[(first, "STAGED", _at(2))],
        documents=[(second, "FAILED", _at(2))],
    )
    _stub_projection_dependencies(monkeypatch)
    service = ProjectService(db)
    service.list = AsyncMock(return_value=([_project_row(first), _project_row(second)], 2))

    data, _total = await service.list_with_readiness()

    assert len(db.calls) == 2  # one query per source, not one per project
    assert all(params == {"ids": [str(first), str(second)]} for _sql, params in db.calls)
    revision_sql = next(sql for sql, _params in db.calls if "knowledge_category_revisions" in sql)
    document_sql = next(sql for sql, _params in db.calls if "knowledge_documents" in sql)
    assert "MAX(r.revision_no)" in revision_sql  # only each category's latest revision counts
    assert "GREATEST(kcr.created_at, kcr.activated_at)" in revision_sql  # freshest artifact wins
    assert "GREATEST(kd.created_at, kd.updated_at)" in document_sql
    assert {row.id: row.ingest_state for row in data} == {first: "ingesting", second: "error"}


class _FakeScalars:
    def __init__(self, rows: list) -> None:
        self._rows = rows

    def all(self) -> list:
        return list(self._rows)

    def first(self):
        return self._rows[0] if self._rows else None


class _CreateDb:
    """Minimal session fake for ProjectService.create: find_by_name → none."""

    def __init__(self) -> None:
        self.added: list = []

    async def scalars(self, statement, *args, **kwargs):
        entity = statement.column_descriptions[0]["entity"]
        return _FakeScalars([row for row in self.added if isinstance(row, entity)])

    def add(self, obj) -> None:
        self.added.append(obj)

    def add_all(self, rows) -> None:
        self.added.extend(rows)

    async def flush(self) -> None:
        for row in self.added:
            if getattr(row, "id", None) is None:
                row.id = uuid.uuid4()
            if hasattr(row, "discovery_revision") and row.discovery_revision is None:
                row.discovery_revision = 0

    async def commit(self) -> None:
        pass

    async def rollback(self) -> None:
        self.added.clear()

    async def refresh(self, obj) -> None:
        pass


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", list(KnowledgeBaseMode))
async def test_created_projects_carry_category_authority(
    monkeypatch: pytest.MonkeyPatch,
    mode: KnowledgeBaseMode,
) -> None:
    """A new project has no legacy card to protect: category authority owns its
    data from birth, so the very first category activation projects."""
    monkeypatch.setattr(project_service, "record_audit", AsyncMock())
    monkeypatch.setattr(project_service, "bump_cache_version", AsyncMock())
    body = ProjectCreate(
        slug=f"amtran-{mode.value.lower()}",
        name=f"Amtran {mode.value}",
        knowledge_mode=mode,
        discovery_card=(
            {"summary": "Tóm tắt sơ bộ"} if mode is KnowledgeBaseMode.DIRECT_CONTEXT else None
        ),
    )

    project = await ProjectService(_CreateDb()).create(body, SimpleNamespace(id=uuid.uuid4()))

    assert project.category_authority_started is True


def _projection_built_project() -> SimpleNamespace:
    """A RAG project whose card the category projection built: the derived
    summary/roles/location plus the preserved keys it seeds as empty lists."""
    card = {
        "summary": "Lắp ráp linh kiện bảng mạch.",
        "roles": ["Công nhân (SMT, PCBA)"],
        "location": "Hải Phòng",
        "eligibility": [],
        "highlights": [],
    }
    return SimpleNamespace(
        id=uuid.uuid4(),
        knowledge_base_id=uuid.uuid4(),
        index_card=card,
        summary=card["summary"],
        discovery_revision=1,
    )


def _update_service_for(
    monkeypatch: pytest.MonkeyPatch,
    project: SimpleNamespace,
    mode: KnowledgeBaseMode,
) -> ProjectService:
    monkeypatch.setattr(project_service, "record_audit", AsyncMock())
    monkeypatch.setattr(project_service, "bump_cache_version", AsyncMock())
    service = ProjectService(SimpleNamespace(commit=AsyncMock(), refresh=AsyncMock()))
    service._require_project = AsyncMock(return_value=project)
    service._knowledge_modes = AsyncMock(
        return_value={project.knowledge_base_id: mode}
    )
    return service


@pytest.mark.asyncio
async def test_discovery_card_patch_merges_into_projection_built_card(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The brief chain PATCHes `highlights` alone onto the projection-built
    card. The apply path must MERGE: a replace would wipe the projection's
    summary/roles/location, which the next re-ingest would only restore on its
    next activation — until then the card lies to the agent."""
    project = _projection_built_project()
    before = dict(project.index_card)
    service = _update_service_for(
        monkeypatch, project, KnowledgeBaseMode.RAG
    )

    await service.update(
        project.id,
        ProjectUpdate(discovery_card={"highlights": ["Đóng BHXH đầy đủ."]}),
        SimpleNamespace(id=uuid.uuid4()),
    )

    # Only the keys present in the patch body changed.
    assert project.index_card == {
        **before,
        "highlights": ["Đóng BHXH đầy đủ."],
    }
    assert project.summary == "Lắp ráp linh kiện bảng mạch."
    assert project.discovery_revision == 2


@pytest.mark.asyncio
async def test_discovery_card_patch_still_refuses_projection_derived_keys(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The merge opens the preserved keys only: a summary/roles/location edit
    on a RAG project would be discarded by the next activation, so it stays
    refused rather than silently lost."""
    project = _projection_built_project()
    before = dict(project.index_card)
    service = _update_service_for(
        monkeypatch, project, KnowledgeBaseMode.RAG
    )

    with pytest.raises(ConflictError):
        await service.update(
            project.id,
            ProjectUpdate(discovery_card={"summary": "Tóm tắt tự gõ tay"}),
            SimpleNamespace(id=uuid.uuid4()),
        )

    assert project.index_card == before
