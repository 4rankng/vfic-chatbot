"""Retired KB fields stay out of admin reads, new writes and cached evidence."""

from datetime import datetime, timezone
import hashlib
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
import uuid

import pytest

from app.api import knowledge as knowledge_api, projects
from app.graph.tools import knowledge
from app.models.knowledge import KnowledgeBaseMode
from app.schemas.knowledge_bases import DirectContextFileUpsert
from app.schemas.knowledge import SearchTestResult
from app.services.knowledge import base_service
from app.services.knowledge.base_service import KnowledgeBaseService
from app.services.project.knowledge_export import export_project_knowledge
from app.shared.domain.errors import ConflictError


LEGACY_SOURCE = (
    'Lương & thu nhập\njob_ids: ["old-role"]\njobs_ids: []\n'
    'vacancies: null\nemployment_type: null\nLương: 6 triệu\n'
)
CLEAN_SOURCE = "Lương & thu nhập\nLương: 6 triệu\n"


def test_admin_search_preview_omits_legacy_fields_and_preserves_similarity():
    source = {"content": LEGACY_SOURCE, "similarity": 0.94}

    result = SearchTestResult.model_validate(source)

    assert result.content == CLEAN_SOURCE
    assert result.similarity == 0.94
    assert source["content"] == LEGACY_SOURCE


def _file(kb_id):
    return SimpleNamespace(
        id=uuid.uuid4(),
        knowledge_base_id=kb_id,
        filename="knowledge.md",
        raw_text=LEGACY_SOURCE,
        normalized_text=LEGACY_SOURCE,
        content_sha256=hashlib.sha256(LEGACY_SOURCE.encode()).hexdigest(),
        char_count=len(LEGACY_SOURCE),
        line_count=len(LEGACY_SOURCE.splitlines()),
        updated_at=datetime.now(timezone.utc),
    )


@pytest.mark.asyncio
async def test_old_direct_file_read_is_clean_without_mutating_saved_identity():
    kb_id = uuid.uuid4()
    row = _file(kb_id)
    db = SimpleNamespace(
        get=AsyncMock(return_value=SimpleNamespace(id=kb_id)), scalar=AsyncMock(return_value=row)
    )

    result = await KnowledgeBaseService(db).get_direct_file_detail(kb_id)

    assert result.text == CLEAN_SOURCE
    assert row.raw_text == LEGACY_SOURCE
    assert row.normalized_text == LEGACY_SOURCE
    assert result.content_sha256 == row.content_sha256
    assert result.char_count == row.char_count


@pytest.mark.asyncio
async def test_project_single_page_api_normalizes_old_source(monkeypatch):
    row = _file(uuid.uuid4())
    service = SimpleNamespace(get_single_page=AsyncMock(return_value=row))
    monkeypatch.setattr(projects, "ProjectService", lambda _db: service)

    result = await projects.get_project_single_page(uuid.uuid4(), _user=object(), db=object())

    assert result.text == CLEAN_SOURCE
    assert row.raw_text == LEGACY_SOURCE
    assert result.content_sha256 == row.content_sha256


@pytest.mark.asyncio
async def test_source_download_is_clean_without_rewriting_stored_upload(monkeypatch):
    row = SimpleNamespace(file_name="original.txt", raw_text=LEGACY_SOURCE)
    monkeypatch.setattr(knowledge_api, "_load", AsyncMock(return_value=row))

    response = await knowledge_api.download_raw_document(uuid.uuid4(), _admin=object(), db=object())

    assert response.body == CLEAN_SOURCE.encode()
    assert row.raw_text == LEGACY_SOURCE
    assert response.headers["content-disposition"].startswith('attachment; filename="original.txt"')


@pytest.mark.asyncio
@pytest.mark.parametrize("replace_existing", [False, True])
async def test_new_direct_file_persists_clean_source_and_matching_stats(
    monkeypatch, replace_existing
):
    kb_id = uuid.uuid4()
    kb = SimpleNamespace(id=kb_id, mode=KnowledgeBaseMode.DIRECT_CONTEXT)
    previous = _file(kb_id) if replace_existing else None
    db = SimpleNamespace(
        get=AsyncMock(return_value=kb),
        scalar=AsyncMock(return_value=previous),
        add=Mock(),
        flush=AsyncMock(),
        commit=AsyncMock(),
        refresh=AsyncMock(),
    )
    monkeypatch.setattr(base_service, "require_direct_context_ready", AsyncMock())
    monkeypatch.setattr(base_service, "record_audit", AsyncMock())

    row = await KnowledgeBaseService(db).upsert_direct_file(
        kb_id,
        DirectContextFileUpsert(filename="knowledge.md", text=LEGACY_SOURCE),
        SimpleNamespace(id=uuid.uuid4()),
    )

    assert row.raw_text == CLEAN_SOURCE
    stats = KnowledgeBaseService.canonical_direct_file_stats(CLEAN_SOURCE)
    assert row.normalized_text == stats.normalized_text
    assert row.content_sha256 == stats.content_sha256
    assert row.char_count == stats.char_count
    assert row.line_count == stats.line_count
    assert db.commit.await_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "source",
    [
        'job_ids: ["old"]\n',
        '{"job_ids": ["old"]}',
        '[{"jobs_ids": ["old"]}]',
        "vacancies: null\nemployment_type: null\n",
        '{"vacancies": 100, "employment_type": "temporary"}',
    ],
)
async def test_direct_file_rejects_reference_only_content_before_write(source):
    kb_id = uuid.uuid4()
    db = SimpleNamespace(
        get=AsyncMock(
            return_value=SimpleNamespace(id=kb_id, mode=KnowledgeBaseMode.DIRECT_CONTEXT)
        ),
        scalar=AsyncMock(),
        add=Mock(),
    )

    with pytest.raises(ConflictError, match="cannot be empty"):
        await KnowledgeBaseService(db).upsert_direct_file(
            kb_id,
            DirectContextFileUpsert(filename="knowledge.md", text=source),
            SimpleNamespace(id=uuid.uuid4()),
        )

    db.scalar.assert_not_awaited()
    db.add.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "source",
    [
        'job_ids: ["old"]',
        '{"job_ids": ["old"]}',
        '[{"jobs_ids": ["old"]}]',
        "vacancies: null\nemployment_type: null\n",
        '{"vacancies": 100, "employment_type": "temporary"}',
    ],
)
async def test_export_rejects_json_or_markdown_with_only_retired_fields(source):
    db = SimpleNamespace(
        execute=AsyncMock(
            return_value=SimpleNamespace(
                mappings=lambda: SimpleNamespace(
                    all=lambda: [{"source_text": source}],
                )
            )
        )
    )

    with pytest.raises(ConflictError, match="chưa có kiến thức"):
        await export_project_knowledge(db, uuid.uuid4())


@pytest.mark.parametrize("source_field", ["content", "source_quote"])
@pytest.mark.parametrize("multiline_json", [False, True])
def test_retrieval_citation_preserves_facts_without_old_fields(source_field, multiline_json):
    source = json.dumps(
        {
            "job_ids": ["old"], "jobs_ids": [], "vacancies": None,
            "employment_type": "temporary", "salary": "6 triệu",
        },
        ensure_ascii=False,
        indent=2 if multiline_json else None,
    )
    row = SimpleNamespace(
        content="unused",
        source_quote=None,
        summary="Thông tin đã lưu",
        metadata={"citation": {"label": "Lương"}},
    )
    setattr(row, source_field, source)
    if source_field == "content":
        row.summary = None

    result = knowledge._format_knowledge_row(row)

    assert "job_ids" not in result and "jobs_ids" not in result
    assert "vacancies" not in result and "employment_type" not in result
    assert "6 triệu" in result
    assert "Nguồn: Lương" in result
    if source_field == "source_quote":
        assert "Tóm tắt: Thông tin đã lưu" in result


@pytest.mark.parametrize(
    "quote", ['job_ids: ["old"]', '{"job_ids": ["old"]}', "vacancies: null\nemployment_type: null"]
)
@pytest.mark.parametrize("summary", [None, 'jobs_ids: ["old"]', "Có hỗ trợ bữa ăn"])
def test_empty_cleaned_quote_and_summary_do_not_hide_factual_chunk_content(quote, summary):
    row = SimpleNamespace(
        content="name: Cơm ca miễn phí",
        source_quote=quote,
        summary=summary,
        metadata={},
    )

    result = knowledge._format_knowledge_row(row)

    assert result.startswith("- name: Cơm ca miễn phí\n")
    assert "job_ids" not in result and "jobs_ids" not in result
    if summary == "Có hỗ trợ bữa ăn":
        assert "Tóm tắt: Có hỗ trợ bữa ăn" in result
    else:
        assert "Tóm tắt:" not in result


@pytest.mark.asyncio
@pytest.mark.parametrize("cache_path", ["exact", "semantic", "coalesced"])
@pytest.mark.parametrize("multiline_json", [False, True])
async def test_old_cached_evidence_is_normalized_before_bot_use(
    monkeypatch, cache_path, multiline_json
):
    from app.graph import semantic_cache

    source = json.dumps(
        {
            "job_ids": ["old"], "jobs_ids": [], "vacancies": None,
            "employment_type": "temporary", "salary": "6 triệu",
        },
        ensure_ascii=False,
        indent=2 if multiline_json else None,
    )
    cached = f"- {source}\n  Nguồn: Lương\n"
    settings = SimpleNamespace(
        rag_cache_enabled=True,
        singleflight_enabled=cache_path == "coalesced",
        semantic_cache_enabled=cache_path == "semantic",
    )
    monkeypatch.setattr(knowledge, "get_settings", lambda: settings)
    monkeypatch.setattr(knowledge, "cache_version", AsyncMock(return_value="1"))
    monkeypatch.setattr(
        knowledge,
        "cache_get_json",
        AsyncMock(return_value=cached if cache_path == "exact" else None),
    )
    monkeypatch.setattr(knowledge, "cached_embed", AsyncMock(return_value=[0.1] * 8))
    monkeypatch.setattr(knowledge, "_search_knowledge_coalesced", AsyncMock(return_value=cached))
    monkeypatch.setattr(
        semantic_cache,
        "semantic_cache_get",
        AsyncMock(return_value=SimpleNamespace(result=cached, similarity=0.99)),
    )
    repo = SimpleNamespace(
        active_project_ids=AsyncMock(return_value=["project"]),
        match_faq=AsyncMock(),
        match_documents=AsyncMock(),
    )

    result = await knowledge.search_knowledge(repo, object(), "lương thế nào")

    assert "job_ids" not in result and "jobs_ids" not in result
    assert "6 triệu" in result and "Nguồn: Lương" in result
    repo.match_faq.assert_not_awaited()
    repo.match_documents.assert_not_awaited()
