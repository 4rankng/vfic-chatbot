import uuid
from types import SimpleNamespace

import pytest

from app.models.user import Role
from app.schemas.projects import ProjectUpdate
from app.services.errors import ForbiddenError
from app.services.project_service import ProjectService


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


class _FakeUpdateDb:
    def __init__(self, project, persona=None):
        self.project = project
        self.persona = persona
        self.added = []
        self.commits = 0
        self.flushes = 0
        self.refreshed = []

    async def get(self, model, row_id):
        if model.__name__ == "Project" and row_id == self.project.id:
            return self.project
        if model.__name__ == "Persona" and self.persona and row_id == self.persona.id:
            return self.persona
        return None

    def add(self, value):
        self.added.append(value)

    async def flush(self):
        self.flushes += 1

    async def commit(self):
        self.commits += 1

    async def refresh(self, value):
        self.refreshed.append(value)


def _actor(role: Role):
    return SimpleNamespace(id=uuid.uuid4(), role=role)


@pytest.mark.asyncio
async def test_project_update_omitted_persona_leaves_assignment_unchanged():
    persona_id = uuid.uuid4()
    project = SimpleNamespace(id=uuid.uuid4(), name="LGD", default_persona_id=persona_id)
    db = _FakeUpdateDb(project)

    await ProjectService(db).update(
        project.id,
        ProjectUpdate(name="LG Display"),
        _actor(Role.recruiter),
    )

    assert project.name == "LG Display"
    assert project.default_persona_id == persona_id


@pytest.mark.asyncio
async def test_project_update_admin_can_clear_persona_assignment():
    persona_id = uuid.uuid4()
    project = SimpleNamespace(id=uuid.uuid4(), name="LGD", default_persona_id=persona_id)
    db = _FakeUpdateDb(project)

    await ProjectService(db).update(
        project.id,
        ProjectUpdate(default_persona_id=None),
        _actor(Role.admin),
    )

    assert project.default_persona_id is None


@pytest.mark.asyncio
async def test_project_update_recruiter_cannot_change_persona_assignment():
    persona_id = uuid.uuid4()
    project = SimpleNamespace(id=uuid.uuid4(), name="LGD", default_persona_id=None)
    persona = SimpleNamespace(id=persona_id)
    db = _FakeUpdateDb(project, persona)

    with pytest.raises(ForbiddenError):
        await ProjectService(db).update(
            project.id,
            ProjectUpdate(default_persona_id=persona_id),
            _actor(Role.recruiter),
        )

    assert project.default_persona_id is None
