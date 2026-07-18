import uuid

import pytest
from pydantic import ValidationError

from app.schemas.projects import ProjectOut, ProjectUpdate
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


def test_project_schemas_no_longer_accept_or_serialize_default_persona_id() -> None:
    with pytest.raises(ValidationError):
        ProjectUpdate.model_validate({"default_persona_id": str(uuid.uuid4())})

    assert "default_persona_id" not in ProjectOut.model_json_schema()["properties"]
