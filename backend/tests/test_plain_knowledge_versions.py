"""Plain knowledge versions remain available without a structured template."""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import app.services.knowledge as knowledge_service_package
import app.services.knowledge.service as knowledge_service_module
from app.models.knowledge import KBVersionStatus
from app.services.knowledge.service import KnowledgeService


async def test_create_plain_knowledge_version_without_a_template_assignment() -> None:
    project_id = uuid.uuid4()
    actor = SimpleNamespace(id=uuid.uuid4())

    class _Database:
        def __init__(self) -> None:
            self.values = [SimpleNamespace(id=project_id), 1]
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
    assert db.values == []


async def test_ingest_legacy_template_bound_version_stays_plain_recruitment_knowledge(
    monkeypatch,
) -> None:
    version = SimpleNamespace(
        id=uuid.uuid4(),
        project_id=uuid.uuid4(),
        template_version_id=uuid.uuid4(),
        status=KBVersionStatus.DRAFT,
        error_message=None,
        release_manifest_sha256=None,
    )
    document = SimpleNamespace(
        id=uuid.uuid4(),
        raw_text=None,
        project_id=None,
        status=None,
        stage=None,
        error=None,
    )
    text_file = SimpleNamespace(
        id=uuid.uuid4(),
        document_id=uuid.uuid4(),
        normalized_text="Tuyển công nhân ca ngày.",
        content_sha256="a" * 64,
        filename="tuyen-dung.md",
    )

    class _Database:
        async def get(self, _model, _id):
            return document

        async def commit(self) -> None:
            return None

        async def refresh(self, _value: object) -> None:
            return None

    class _Chunks:
        def __init__(self, _db: object) -> None:
            pass

        async def clear_version(self, _version_id: uuid.UUID) -> None:
            return None

        async def attach_doc_chunks_to_file(self, **_kwargs: object) -> None:
            return None

    class _Pipeline:
        def __init__(self, _db: object, _embedder: object, _llm: object) -> None:
            pass

        async def run(self, _document: object) -> None:
            return None

    service = KnowledgeService(_Database())

    async def list_files(_version_id: uuid.UUID):
        return [text_file]

    monkeypatch.setattr(service, "list_version_files", list_files)
    monkeypatch.setattr(knowledge_service_module, "KnowledgeChunkRepo", _Chunks)
    monkeypatch.setattr(knowledge_service_package, "KnowledgePipeline", _Pipeline)

    result = await service.ingest_version(lambda _text: None, version, llm_json=lambda *_: None)

    assert result is version
    assert version.status is KBVersionStatus.READY
    assert version.release_manifest_sha256 is not None
