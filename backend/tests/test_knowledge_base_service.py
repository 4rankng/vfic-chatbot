"""Standalone KB service invariants without external I/O."""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

from app.models.knowledge import KnowledgeBaseMode
from app.schemas.knowledge_bases import (
    MAX_DIRECT_CONTEXT_CHARS,
    DirectContextFileUpsert,
    KnowledgeBaseCreate,
    LegacyKnowledgeBootstrap,
)
from app.services.errors import ConflictError
from app.services import knowledge_base_service
from app.services.knowledge_base_service import KnowledgeBaseService
from app.services import knowledge_base_capacity


class _Db:
    def __init__(self, *, get_values: dict[tuple[str, uuid.UUID], object | None], scalars=None):
        self.get_values = get_values
        self.scalar_values: list[object | None] = []
        self.scalars_value = scalars
        self.added: list[object] = []
        self.commits = 0

    async def get(self, model, row_id):
        return self.get_values.get((model.__name__, row_id))

    async def scalar(self, _statement):
        return self.scalar_values.pop(0) if self.scalar_values else None

    async def scalars(self, _statement):
        return SimpleNamespace(all=lambda: self.scalars_value or [])

    def add(self, value):
        self.added.append(value)

    def add_all(self, values):
        self.added.extend(values)

    async def flush(self):
        return None

    async def commit(self):
        self.commits += 1

    async def refresh(self, _value):
        return None


def _actor():
    return SimpleNamespace(id=uuid.uuid4())


@pytest.mark.asyncio
async def test_direct_file_rejects_rag_knowledge_base() -> None:
    kb_id = uuid.uuid4()
    kb = SimpleNamespace(id=kb_id, mode=KnowledgeBaseMode.RAG)
    db = _Db(get_values={("KnowledgeBase", kb_id): kb})

    with pytest.raises(ConflictError, match="direct-context"):
        await KnowledgeBaseService(db).upsert_direct_file(
            kb_id,
            DirectContextFileUpsert(filename="context.txt", text="Hello"),
            _actor(),
        )


@pytest.mark.asyncio
async def test_direct_file_preserves_raw_text_and_stores_normalized_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    kb_id = uuid.uuid4()
    kb = SimpleNamespace(id=kb_id, mode=KnowledgeBaseMode.DIRECT_CONTEXT)
    db = _Db(get_values={("KnowledgeBase", kb_id): kb})
    raw_text = "\ufeffDòng một\r\n\r\n\r\n\r\nDòng hai\r"

    async def ready(_db, _knowledge_base) -> None:
        return None

    async def audit(*args, **kwargs) -> None:
        return None

    monkeypatch.setattr(knowledge_base_service, "require_direct_context_ready", ready)
    monkeypatch.setattr(knowledge_base_service, "record_audit", audit)

    direct_file = await KnowledgeBaseService(db).upsert_direct_file(
        kb_id,
        DirectContextFileUpsert(filename="context.md", text=raw_text),
        _actor(),
    )

    assert direct_file.raw_text == raw_text
    assert direct_file.normalized_text == "Dòng một\n\n\nDòng hai"
    assert direct_file.content_sha256
    assert db.commits == 1


@pytest.mark.asyncio
async def test_project_attachment_is_disabled_for_project_owned_modes() -> None:
    kb_id = uuid.uuid4()
    kb = SimpleNamespace(id=kb_id, mode=KnowledgeBaseMode.DIRECT_CONTEXT)
    db = _Db(get_values={("KnowledgeBase", kb_id): kb})

    with pytest.raises(ConflictError, match="Projects own their knowledge mode"):
        await KnowledgeBaseService(db).attach_project(kb_id, uuid.uuid4(), _actor())


@pytest.mark.asyncio
async def test_bootstrap_reuses_existing_rag_kb_and_preserves_live_references() -> None:
    persona_id = uuid.uuid4()
    kb_id = uuid.uuid4()
    project_id = uuid.uuid4()
    kb = SimpleNamespace(id=kb_id, slug="shared", mode=KnowledgeBaseMode.RAG, project_id=None)
    persona = SimpleNamespace(
        id=persona_id,
        knowledge_base_id=None,
        name="Old name",
        slug="old-name",
    )
    project = SimpleNamespace(id=project_id, knowledge_base_id=None)
    db = _Db(
        get_values={("Persona", persona_id): persona},
        scalars=[project],
    )
    db.scalar_values = [kb]

    result = await KnowledgeBaseService(db).bootstrap_legacy(
        LegacyKnowledgeBootstrap(
            persona_id=persona_id,
            knowledge_base_name="Shared KB",
            knowledge_base_slug="shared",
            project_ids=[project_id],
            persona_name="Default",
            persona_slug="default",
        ),
        _actor(),
    )

    assert result is kb
    assert persona.knowledge_base_id == kb_id
    assert project.knowledge_base_id == kb_id
    assert kb.project_id == project_id
    assert persona.name == "Default"
    assert persona.slug == "default"
    assert db.commits == 1


def test_direct_context_file_requires_a_text_filename() -> None:
    with pytest.raises(ValueError, match=".txt or .md"):
        DirectContextFileUpsert(filename="knowledge.pdf", text="not supported")


def test_direct_context_file_rejects_oversized_text_at_request_boundary() -> None:
    with pytest.raises(ValueError, match="at most 300000 characters"):
        DirectContextFileUpsert(
            filename="knowledge.md",
            text="x" * (MAX_DIRECT_CONTEXT_CHARS + 1),
        )


def test_rag_kb_schema_accepts_tenant_neutral_names() -> None:
    kb = KnowledgeBaseCreate(name="Customer knowledge", slug="customer-knowledge", mode="RAG")
    assert kb.mode is KnowledgeBaseMode.RAG


@pytest.mark.asyncio
async def test_direct_context_capacity_uses_active_model_window(monkeypatch) -> None:
    async def active_model(_db):
        return "minimax", "MiniMax-M2.7-highspeed", 204_800

    monkeypatch.setattr(knowledge_base_capacity, "_active_model_context", active_model)
    direct_file = SimpleNamespace(normalized_text="x" * 100_000)

    capacity = await knowledge_base_capacity.direct_context_capacity(
        SimpleNamespace(), direct_file, agent_markdown="Agent instructions"
    )

    assert capacity.provider == "minimax"
    assert capacity.model == "MiniMax-M2.7-highspeed"
    assert capacity.context_window_tokens == 204_800
    assert capacity.estimated_input_tokens == 50_000
    assert capacity.fits


@pytest.mark.asyncio
async def test_direct_context_readiness_rejects_missing_file() -> None:
    kb = SimpleNamespace(id=uuid.uuid4(), mode=KnowledgeBaseMode.DIRECT_CONTEXT)
    db = _Db(get_values={})

    with pytest.raises(ConflictError, match="needs one text file"):
        await knowledge_base_capacity.require_direct_context_ready(db, kb)
