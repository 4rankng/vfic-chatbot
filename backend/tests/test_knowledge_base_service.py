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
from app.shared.domain.errors import ConflictError
from app.services.knowledge import base_service
from app.services.knowledge.base_service import KnowledgeBaseService
from app.services import knowledge_base_capacity


class _Db:
    def __init__(
        self,
        *,
        get_values: dict[tuple[str, uuid.UUID], object | None],
        scalars=None,
        execute_rows: list[list[tuple]] | None = None,
    ):
        self.get_values = get_values
        self.scalar_values: list[object | None] = []
        self.scalars_value = scalars
        self.added: list[object] = []
        self.commits = 0
        self.execute_rows = list(execute_rows or [])
        self.executed_statements: list[object] = []

    async def get(self, model, row_id):
        return self.get_values.get((model.__name__, row_id))

    async def scalar(self, _statement):
        return self.scalar_values.pop(0) if self.scalar_values else None

    async def scalars(self, _statement):
        return SimpleNamespace(all=lambda: self.scalars_value or [])

    async def execute(self, statement):
        self.executed_statements.append(statement)
        rows = self.execute_rows.pop(0) if self.execute_rows else []
        return SimpleNamespace(all=lambda: rows)

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

    monkeypatch.setattr(base_service, "require_direct_context_ready", ready)
    monkeypatch.setattr(base_service, "record_audit", audit)

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
async def test_bootstrap_reuses_existing_rag_kb_and_preserves_live_references(
    monkeypatch,
) -> None:
    kb_id = uuid.uuid4()
    project_id = uuid.uuid4()
    kb = SimpleNamespace(id=kb_id, slug="shared", mode=KnowledgeBaseMode.RAG, project_id=None)
    project = SimpleNamespace(id=project_id, knowledge_base_id=None)
    db = _Db(get_values={}, scalars=[project])
    db.scalar_values = [kb]

    bumps: list[str] = []

    async def record_bump(namespace):
        bumps.append(namespace)

    monkeypatch.setattr(base_service, "bump_cache_version", record_bump)

    result = await KnowledgeBaseService(db).bootstrap_legacy(
        LegacyKnowledgeBootstrap(
            knowledge_base_name="Shared KB",
            knowledge_base_slug="shared",
            project_ids=[project_id],
        ),
        _actor(),
    )

    assert result is kb
    assert project.knowledge_base_id == kb_id
    assert kb.project_id == project_id
    assert db.commits == 1
    # The attach invalidates the direct-context routing catalog like any
    # project write: one preamble bump, after the commit lands.
    assert bumps == [base_service.NS_PREAMBLE]


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
async def test_project_job_count_selects_only_current_category_authority() -> None:
    kb_id = uuid.uuid4()
    project = SimpleNamespace(
        id=uuid.uuid4(),
        slug="alpha",
        name="Alpha",
        is_active=True,
    )
    db = _Db(
        get_values={
            (
                "KnowledgeBase",
                kb_id,
            ): SimpleNamespace(id=kb_id, mode=KnowledgeBaseMode.RAG)
        },
        scalars=[project],
        execute_rows=[[], [], []],
    )

    result = await KnowledgeBaseService(db).list_projects(kb_id)

    assert result[0].active_job_count == 0
    job_sql = str(db.executed_statements[-1].compile(compile_kwargs={"literal_binds": True})).lower()
    assert "projects.category_authority_started is true" in job_sql
    assert "jobs.source_category_revision_id is not null" in job_sql
    assert "projects.category_authority_started is false" in job_sql
    assert "jobs.source_category_revision_id is null" in job_sql
    assert "coalesce(jobs.vacancy_count, 1) > 0" in job_sql
    assert "knowledge_categories.active_revision_id = jobs.source_category_revision_id" in job_sql
    assert "knowledge_categories.category_key = 'jobs'" in job_sql
    assert "exists" in job_sql


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


@pytest.mark.asyncio
async def test_direct_context_readiness_accepts_present_file(monkeypatch) -> None:
    """Admin callers keep the preserved path: the file row is fetched inside
    the guard and the capacity is computed on it."""
    kb = SimpleNamespace(id=uuid.uuid4(), mode=KnowledgeBaseMode.DIRECT_CONTEXT)
    db = _Db(get_values={})
    db.scalar_values.append(SimpleNamespace(normalized_text="x"))
    async def active_model(_db):
        return "minimax", "MiniMax-M2.7-highspeed", 1_024_000

    monkeypatch.setattr(knowledge_base_capacity, "_active_model_context", active_model)

    capacity = await knowledge_base_capacity.require_direct_context_ready(db, kb)
    assert capacity.estimated_input_tokens == 1
    assert capacity.fits


@pytest.mark.asyncio
async def test_ensure_direct_context_fits_returns_capacity_and_raises_over_limit(
    monkeypatch,
) -> None:
    async def active_model(_db):
        return "minimax", "MiniMax-M2.7-highspeed", 1_024_000

    monkeypatch.setattr(knowledge_base_capacity, "_active_model_context", active_model)

    fitting = SimpleNamespace(normalized_text="x" * 100)
    capacity = await knowledge_base_capacity.ensure_direct_context_fits(
        SimpleNamespace(), fitting, agent_markdown="a" * 10
    )
    assert capacity.estimated_input_tokens == 50
    assert capacity.fits

    oversized = SimpleNamespace(normalized_text="x" * 2_100_000)
    with pytest.raises(ConflictError, match="does not fit"):
        await knowledge_base_capacity.ensure_direct_context_fits(
            SimpleNamespace(), oversized, agent_markdown="a" * 10
        )


@pytest.mark.asyncio
async def test_active_model_context_uses_the_chatbot_window_for_every_provider(monkeypatch) -> None:
    """Every chatbot agent resolves the same fixed window, on any provider.

    The window is a deployment property, not an operator setting and not a
    per-model lookup: no settings row may shrink it, and no vendor registry or
    metadata call may fail the resolution.
    """
    from app.services.integration_settings import (
        CustomLlmRuntimeConfig,
        IntegrationSettingsService,
        MinimaxRuntimeConfig,
        OpenRouterRuntimeConfig,
    )

    def minimax_with(provider: str, model: str = "MiniMax-M2.7-highspeed"):
        async def _resolve(self):
            return MinimaxRuntimeConfig(default_provider=provider, agent_model=model)

        return _resolve

    async def fake_custom(self):
        return CustomLlmRuntimeConfig(agent_model="mimo-v2.5-pro")

    async def fake_openrouter(self):
        return OpenRouterRuntimeConfig(agent_model="z-ai/glm-4.6")

    monkeypatch.setattr(IntegrationSettingsService, "resolve_custom_llm", fake_custom)
    monkeypatch.setattr(IntegrationSettingsService, "resolve_openrouter", fake_openrouter)

    cases = (
        (minimax_with("minimax"), "minimax", "MiniMax-M2.7-highspeed"),
        # A model name the old registry did not know: it used to raise ConflictError.
        (minimax_with("minimax", "minimax-m9-turbo"), "minimax", "minimax-m9-turbo"),
        (minimax_with("custom"), "custom", "mimo-v2.5-pro"),
        (minimax_with("openrouter"), "openrouter", "z-ai/glm-4.6"),
    )

    for resolver, expected_provider, expected_model in cases:
        monkeypatch.setattr(IntegrationSettingsService, "resolve_minimax", resolver)
        provider, model, window = await knowledge_base_capacity._active_model_context(
            SimpleNamespace()
        )
        assert (provider, model) == (expected_provider, expected_model)
        assert window == knowledge_base_capacity._CHATBOT_CONTEXT_WINDOW_TOKENS
        assert window == 1_024_000
