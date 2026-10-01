"""Retrieval scopes fail closed and citations keep project attribution."""

from types import SimpleNamespace
from unittest.mock import AsyncMock
import uuid

import pytest

from app.graph.tools.knowledge import _format_knowledge_row, _render_capped_evidence, search_knowledge
from app.project_knowledge.domain.category_catalog import CATEGORY_DEFINITIONS
from app.services.retrieval.catalog_repository import CatalogRepository
from app.services.retrieval.document_repository import DocumentRepository
from app.services.retrieval.faq_repository import FaqRepository
from app.services.retrieval.repository import RetrievalRepository


@pytest.mark.parametrize("kind", ["documents", "faq"])
async def test_empty_project_scope_never_reads_global_evidence(kind):
    db = SimpleNamespace(execute=AsyncMock())
    if kind == "documents":
        result = await DocumentRepository(db).match_documents("vector", 10, "{}", project_ids=[])
    else:
        result = await FaqRepository(db).match_faq("vector", project_ids=[])
    assert result == []
    db.execute.assert_not_awaited()


@pytest.mark.parametrize("kind", ["documents", "faq"])
@pytest.mark.parametrize("requested", [None, "assigned", "other", "empty"])
async def test_page_scope_is_enforced_at_the_retrieval_port(kind, requested):
    assigned, other = str(uuid.uuid4()), str(uuid.uuid4())
    scope = {None: None, "assigned": [assigned], "other": [other], "empty": []}[requested]
    repo = RetrievalRepository(SimpleNamespace(), page_project_ids=(assigned,))
    documents = AsyncMock(return_value=[])
    faq = AsyncMock(return_value=[])
    repo._documents.match_documents = documents
    repo._faq.match_faq = faq
    if kind == "documents":
        await repo.match_documents("vector", 10, "{}", project_ids=scope)
        call = documents.await_args
    else:
        await repo.match_faq("vector", project_ids=scope)
        call = faq.await_args
    assert call.kwargs["project_ids"] == ([assigned] if requested in (None, "assigned") else [])


async def test_page_active_ids_are_checked_against_current_catalog():
    assigned = str(uuid.uuid4())
    db = SimpleNamespace(scalars=AsyncMock(return_value=iter(())))
    repo = CatalogRepository(db, page_project_ids=(assigned,))
    assert await repo.active_project_ids() == []
    db.scalars.assert_awaited_once()
    statement = str(db.scalars.await_args.args[0])
    assert "is_active" in statement
    assert "knowledge_base_id IS NOT NULL" in statement


def test_citations_identify_the_project_and_category():
    row = SimpleNamespace(
        content="Thu nhập từ 10 triệu", source_quote=None, summary=None, metadata={},
        project_name="Nhà máy A", project_slug="factory-a", category="compensation",
    )
    output = _format_knowledge_row(row)
    assert "Nhà máy A" in output
    assert "factory-a" in output
    assert "compensation" in output


def test_large_top_hit_does_not_consume_evidence_for_the_other_categories():
    rows = [
        SimpleNamespace(
            content="x" * (90000 if index == 0 else 100),
            source_quote=None, summary=None, metadata={"citation": {"label": category}},
        )
        for index, category in enumerate(definition.key.value for definition in CATEGORY_DEFINITIONS)
    ]
    rendered = _render_capped_evidence(rows)
    assert len(rendered) == 12
    assert "Nguồn: jobs" in rendered[0]
    assert "Nguồn: faq" in rendered[-1]
    assert sum(map(len, rendered)) <= 20000


@pytest.mark.parametrize("degraded", [None, "retrieval_vector_failed"])
@pytest.mark.parametrize("enabled", [False, True])
async def test_absent_evidence_is_cached_only_after_a_successful_enabled_read(
    monkeypatch, degraded, enabled,
):
    import app.graph.tools.knowledge as knowledge

    monkeypatch.setattr(knowledge, "get_settings", lambda: SimpleNamespace(
        rag_cache_enabled=enabled, rag_result_cache_ttl_seconds=60,
    ))
    monkeypatch.setattr(knowledge, "cache_get_json", AsyncMock(return_value=None))
    monkeypatch.setattr(knowledge, "cache_version", AsyncMock(return_value="1"))
    monkeypatch.setattr(knowledge, "cached_embed", AsyncMock(return_value=[0.1]))
    cache_write = AsyncMock()
    monkeypatch.setattr(knowledge, "cache_set_json", cache_write)
    repo = SimpleNamespace(
        active_project_ids=AsyncMock(return_value=["p1"]),
        match_faq=AsyncMock(return_value=[]), match_documents=AsyncMock(return_value=[]),
        last_match_degraded=degraded,
    )
    await search_knowledge(repo, AsyncMock(), "thu nhập")
    assert cache_write.await_count == int(enabled and degraded is None)


async def test_partial_faq_evidence_survives_a_vector_failure_without_caching(monkeypatch):
    import app.graph.semantic_cache as semantic
    import app.graph.tools.knowledge as knowledge

    monkeypatch.setattr(knowledge, "get_settings", lambda: SimpleNamespace(
        rag_cache_enabled=True, semantic_cache_enabled=True, rag_result_cache_ttl_seconds=60,
    ))
    monkeypatch.setattr(knowledge, "cache_get_json", AsyncMock(return_value=None))
    monkeypatch.setattr(knowledge, "cache_version", AsyncMock(return_value="1"))
    monkeypatch.setattr(knowledge, "cached_embed", AsyncMock(return_value=[0.1]))
    cache_write = AsyncMock()
    semantic_write = AsyncMock()
    monkeypatch.setattr(knowledge, "cache_set_json", cache_write)
    monkeypatch.setattr(semantic, "semantic_cache_get", AsyncMock(return_value=None))
    monkeypatch.setattr(semantic, "semantic_cache_put", semantic_write)
    faq = SimpleNamespace(id="faq", content="Published FAQ", metadata={}, source_quote=None)
    repo = SimpleNamespace(
        active_project_ids=AsyncMock(return_value=["p1"]),
        match_faq=AsyncMock(return_value=[faq]), match_documents=AsyncMock(return_value=[]),
        last_match_degraded="retrieval_vector_failed",
    )
    assert "Published FAQ" in await search_knowledge(repo, AsyncMock(), "thu nhập")
    cache_write.assert_not_awaited()
    semantic_write.assert_not_awaited()
