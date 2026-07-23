import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from pydantic import ValidationError

from app.models.knowledge import KnowledgeBaseMode
from app.schemas.knowledge_bases import DirectContextFileUpsert
from app.schemas.projects import ProjectOut, ProjectUpdate
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
    direct_file = SimpleNamespace(id=uuid.uuid4())
    upsert_direct_file = AsyncMock(return_value=direct_file)
    audit = AsyncMock()
    bump = AsyncMock()
    monkeypatch.setattr(project_service, "record_audit", audit)
    monkeypatch.setattr(project_service, "bump_cache_version", bump)

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
    bump.assert_awaited_once_with(project_service.NS_PREAMBLE)


@pytest.mark.asyncio
async def test_knowledge_document_count_includes_direct_context_page() -> None:
    project_id = uuid.uuid4()
    db = _FakeDb([SimpleNamespace(project_id=project_id, file_count=1)])

    counts = await ProjectRepository(db).knowledge_document_counts([project_id])

    assert counts == {project_id: 1}
    assert "knowledge_base_direct_files" in str(db.statement)
