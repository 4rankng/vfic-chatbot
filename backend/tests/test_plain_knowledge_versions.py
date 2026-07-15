"""Plain knowledge versions remain available without a structured template."""

from __future__ import annotations

import uuid
from types import SimpleNamespace

from app.models.knowledge import KBVersionStatus
from app.services.knowledge.service import KnowledgeService


async def test_create_plain_knowledge_version_without_a_template_assignment() -> None:
    project_id = uuid.uuid4()
    actor = SimpleNamespace(id=uuid.uuid4())

    class _Database:
        def __init__(self) -> None:
            self.values = [SimpleNamespace(id=project_id), 1, None]
            self.added: list[object] = []

        async def scalar(self, _statement):
            return self.values.pop(0)

        def add(self, value: object) -> None:
            self.added.append(value)

        async def commit(self) -> None:
            return None

        async def refresh(self, _value: object) -> None:
            return None

    db = _Database()

    version = await KnowledgeService(db).create_version(project_id, actor=actor)

    assert version.project_id == project_id
    assert version.status == KBVersionStatus.DRAFT
    assert version.template_version_id is None
