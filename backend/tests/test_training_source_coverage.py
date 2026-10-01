"""Training must retain source facts and reject ungrounded model digests."""

import json
import unicodedata
from types import SimpleNamespace
from unittest.mock import AsyncMock
from unittest.mock import MagicMock
import threading

import pytest

from app.services.knowledge.pipeline import KnowledgePipeline


def _pipeline(llm):
    return KnowledgePipeline(AsyncMock(), AsyncMock(), llm, call_timeout=1)


@pytest.mark.parametrize("quote", [None, "Ký túc xá miễn phí", ""])
async def test_ungrounded_digest_retries_then_preserves_source(quote):
    source = "Ký túc xá: 300.000 đồng/tháng."
    llm = AsyncMock(return_value=json.dumps({
        "units": [{"content": "Ký túc xá miễn phí", "source_quote": quote}]
    }))
    _summary, units = await _pipeline(llm)._digest_section(source)
    assert llm.await_count == 2
    assert units[0]["content"] == source
    assert units[0]["source_quote"] in source


async def test_empty_model_digest_cannot_discard_a_nonempty_source():
    source = "Bảo hiểm: BHXH từ tháng thứ 2."
    llm = AsyncMock(return_value='{"units": []}')
    _summary, units = await _pipeline(llm)._digest_section(source)
    assert llm.await_count == 2
    assert units[0]["content"] == source


async def test_digest_quote_accepts_unicode_and_source_whitespace():
    source = "Công ty cấp\ncơm ca miễn phí."
    quote = "cơm ca miễn phí"

    llm = AsyncMock(return_value=json.dumps({
        "units": [{"content": "Cơm ca miễn phí", "source_quote": unicodedata.normalize("NFD", quote)}]
    }))
    _summary, units = await _pipeline(llm)._digest_section(source)
    assert llm.await_count == 1
    assert units[0]["content"] == "Cơm ca miễn phí"


async def test_digest_cap_keeps_the_remaining_source_searchable(monkeypatch):
    from app.services.knowledge.extraction import DigestSections

    source = "Vị trí công nhân.\n\nHotline cuối tài liệu: 0900000000."
    head = "Vị trí công nhân."
    dropped = len(source) - len(head)
    monkeypatch.setattr(
        "app.services.knowledge.pipeline.split_for_digest",
        lambda _source: DigestSections([head], True, dropped, len(source)),
    )
    pipeline = _pipeline(AsyncMock())
    pipeline._digest_section = AsyncMock(return_value=(head, [{"content": head, "confidence": "high", "is_inference": False}]))
    pipeline._store_units = AsyncMock()
    pipeline._set_stage = AsyncMock()
    doc = SimpleNamespace(id="coverage", raw_text=source, metadata_={}, project_id=None, digest_meta={})
    monkeypatch.setattr("app.services.knowledge.pipeline.rebuild_bus_timetable", AsyncMock())
    await pipeline.run(doc)
    units = pipeline._store_units.await_args.args[1]
    assert any("0900000000" in unit["content"] for unit in units)
    assert doc.digest_meta["dropped_chars"] == 0
    assert doc.digest_meta["truncated"] is False


async def test_upload_extraction_and_original_storage_run_off_the_event_loop(monkeypatch):
    from app.services.knowledge.service import KnowledgeService

    loop_thread = threading.get_ident()
    worker_threads = []

    def extract(_name, _mime, _data):
        worker_threads.append(threading.get_ident())
        return "Nội dung dự án", {"format": "txt"}

    def persist(_name, _data):
        worker_threads.append(threading.get_ident())
        return "/tmp/retained-kb.txt"

    monkeypatch.setattr(KnowledgeService, "_extract_upload_text", staticmethod(extract))
    monkeypatch.setattr("app.services.knowledge.service.persist_original_upload", persist)
    db = AsyncMock()
    db.add = MagicMock()
    service = KnowledgeService(db)
    service.assert_mutable = AsyncMock()
    document = await service.upload_bytes("kb.txt", "text/plain", b"source")
    assert document.raw_text == "Nội dung dự án"
    assert len(worker_threads) == 2
    assert all(worker != loop_thread for worker in worker_threads)


def test_fallback_keeps_end_of_block_facts_in_actual_bot_evidence():
    from app.graph.tools.knowledge import _format_knowledge_row
    from app.services.knowledge.pipeline import _fallback_unit

    source = "Thông tin dự án. " + "a" * 1050 + " Lương: 8.500.000 đồng/tháng."
    unit = _fallback_unit(source, 0)
    rendered = _format_knowledge_row(SimpleNamespace(**unit))
    assert "Lương: 8.500.000 đồng/tháng." in rendered
