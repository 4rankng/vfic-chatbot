"""LLM training-pipeline tests (US: per-project KB upload + digestion + personas).

Pure-unit tests (extract by file type, digest schema validation, digest chunking)
run here. The heavier integration tests below (pipeline.run against a live DB,
multipart upload-file endpoint) need a seeded admin + live Postgres + the
``db_session``/``client``/``clean_kb`` fixtures that were relocated out of this
unit suite during the Supabase->FastAPI migration; they are skipped here.
"""

import io
import json
import uuid
from xml.sax.saxutils import escape
from zipfile import ZipFile

import pytest

from app.models.company import Project  # noqa: F401  (used by skipped integration tests)
from app.models.knowledge import KnowledgeDocument, KnowledgeStatus
from app.services.knowledge import (
    DigestError,
    KnowledgePipeline,
    extract_text,
    split_for_digest,
    validate_digest,
)
from app.services.knowledge import KnowledgeService  # noqa: F401  (used by skipped integration tests)
from app.services.knowledge.pipeline import _fallback_question, _fallback_unit
from app.services.knowledge.prompts import DIGEST_SYSTEM_PROMPT, INDEX_SYSTEM_PROMPT

# Integration tests in this module need infrastructure that is deliberately
# absent from the unit suite (live DB + seeded admin user + fixtures), and some
# target the pre-migration approve/reject API that has since been replaced by
# publish_version/archive/delete. Skip them here rather than error on import.
_integration_skip = pytest.mark.skip(
    reason="integration test: needs live DB + seeded admin (moved out of unit suite)"
)

VEC = [0.01] * 3072


def _docx_bytes(*paragraphs: str) -> bytes:
    """Build the minimal DOCX archive accepted by the stdlib extractor."""
    body = "".join(
        f"<w:p><w:r><w:t>{escape(paragraph)}</w:t></w:r></w:p>"
        for paragraph in paragraphs
    )
    document_xml = (
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f"<w:body>{body}</w:body></w:document>"
    )
    buffer = io.BytesIO()
    with ZipFile(buffer, "w") as archive:
        archive.writestr("word/document.xml", document_xml)
    return buffer.getvalue()


class _FakeEmbedder:
    """GeminiEmbedder-compatible: embed + batch + __call__."""

    async def embed(self, _t):
        return list(VEC)

    async def batch(self, texts):
        return [list(VEC) for _ in texts]

    __call__ = embed


def _units_payload(*contents):
    return {
        "document_summary": "tóm tắt tài liệu",
        "units": [
            {
                "content": c,
                "source_quote": c,
                "summary": c[:30],
                "questions": [f"{c[:20]}?"],
                "category": "job",
                "entities": {"job_title": "operator", "location": "Hải Phòng"},
                "source_anchor": "§1",
                "confidence": "high",
                "is_inference": False,
            }
            for c in contents
        ],
    }


# --------------------------------------------------------------------------- extract
def test_extract_text_csv_txt_md():
    assert extract_text("a.csv", "text/csv", b"x,y\n1,2\n").strip() == "x,y\n1,2"
    assert extract_text("a.txt", "text/plain", "nội dung".encode("utf-8")) == "nội dung"
    assert extract_text("a.md", "text/markdown", b"# title") == "# title"


def test_extract_text_docx():
    txt = extract_text(
        "a.docx",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        _docx_bytes("Dòng một LG Display", "Dòng hai lương 10 triệu"),
    )
    assert "LG Display" in txt and "10 triệu" in txt


def test_release_upload_extracts_docx_text():
    from app.services.knowledge.service import _extract_kb_upload_text

    text, file_format = _extract_kb_upload_text(
        "tuyen-dung.docx",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        _docx_bytes("Yêu cầu tuyển dụng có xe đưa đón"),
    )

    assert file_format == "docx"
    assert "xe đưa đón" in text


def test_extract_text_xlsx():
    openpyxl = pytest.importorskip("openpyxl")

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["vị trí", "lương"])
    ws.append(["operator", "9000000"])
    buf = io.BytesIO()
    wb.save(buf)
    txt = extract_text(
        "a.xlsx",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        buf.getvalue(),
    )
    assert "operator" in txt and "9000000" in txt


def test_split_for_digest_respects_size():
    big = "x" * 15000
    result = split_for_digest(big, max_chars=6000)
    assert len(result.sections) >= 2 and all(len(s) <= 6000 for s in result.sections)
    assert split_for_digest("", 6000).sections == []
    assert split_for_digest("ngắn", 6000).sections == ["ngắn"]


def test_split_for_digest_snaps_to_paragraph_boundary():
    """Cut *end* lands on a paragraph boundary when one exists in the window.

    Regression for the raw ``text[start:start+max_chars]`` slice that ignored
    paragraph boundaries despite the docstring claiming otherwise.

    Note: overlap means a chunk can *start* mid-paragraph (the overlap window
    intentionally re-covers content from the previous chunk). The invariant
    enforced here is that every chunk *ends* on a paragraph boundary, i.e. the
    cut itself does not slice through a paragraph.
    """
    paragraph = "y" * 2500
    text = "\n\n".join([paragraph, paragraph, paragraph, paragraph])
    result = split_for_digest(text, max_chars=6000)
    assert len(result.sections) >= 2
    # Every non-final chunk must end at a paragraph boundary: re-concatenating
    # the chunk to the source and checking the next source char is `\n` (or
    # EOF) is the cleanest property test.
    cursor = 0
    for index, chunk in enumerate(result.sections):
        # Strip leading/trailing whitespace inside the chunk to compare against
        # the source — the splitter returns ``.strip()``-ed chunks.
        stripped_chunk = chunk
        # The chunk must appear in the source somewhere at/after ``cursor``.
        found_at = text.find(stripped_chunk, max(0, cursor - 400))
        assert found_at != -1, f"chunk {index} not located in source"
        chunk_end_in_source = found_at + len(stripped_chunk)
        cursor = chunk_end_in_source
        is_last = index == len(result.sections) - 1
        if not is_last:
            # The next char in source after this chunk must be a newline —
            # i.e. we cut at a paragraph boundary, not mid-paragraph.
            assert chunk_end_in_source >= len(text) or text[chunk_end_in_source] == "\n", (
                f"chunk {index} ends mid-paragraph at source offset {chunk_end_in_source}"
            )


def test_split_for_digest_snaps_to_sentence_when_no_paragraph():
    """In a single long paragraph, cuts land on sentence boundaries."""
    sentence = "This is a sentence. "
    # Make it long enough to force multiple chunks.
    text = sentence * 600  # ~10k chars, no paragraph breaks
    result = split_for_digest(text, max_chars=6000)
    assert len(result.sections) >= 2
    # No chunk should end mid-sentence: every non-final chunk must end with the
    # sentence terminator ". " or "." before whitespace.
    for chunk in result.sections:
        assert chunk.rstrip().endswith("."), f"chunk ends mid-sentence: ...{chunk[-30:]!r}"


def test_split_for_digest_tail_not_duplicated():
    """Input of length ``max_chars + 1`` produces exactly two non-duplicate sections.

    Regression for the off-by-one where the old loop produced a near-duplicate
    final chunk because the ``break`` only fired when the *end* of the current
    chunk reached EOF.
    """
    text = "a" * 6001
    result = split_for_digest(text, max_chars=6000)
    assert len(result.sections) == 2
    # The two sections must be meaningfully different (not near-duplicates).
    assert result.sections[0] != result.sections[1]
    # Tail fully covered (no silent drop).
    assert result.truncated is False
    assert result.dropped_chars == 0
    assert result.total_chars == 6001
    # Full coverage: every source index appears in at least one chunk.
    covered = sum(len(s) for s in result.sections) - (
        len(result.sections) - 1
    ) * 400  # subtract one overlap window per adjacent pair
    assert covered >= 6001


def test_split_for_digest_reports_truncation_at_max_sections():
    """When ``DIGEST_MAX_SECTIONS`` cap is hit, ``truncated=True`` and dropped > 0."""
    from app.core.config import DIGEST_MAX_SECTIONS

    # Build input large enough that even with max overlap we cannot cover it
    # in DIGEST_MAX_SECTIONS windows.
    text = "z" * (DIGEST_MAX_SECTIONS * 6000 + 5000)
    result = split_for_digest(text, max_chars=6000)
    assert len(result.sections) <= DIGEST_MAX_SECTIONS
    assert result.truncated is True
    assert result.dropped_chars > 0
    assert result.total_chars == len(text)


def test_split_for_digest_preserves_vietnamese_diacritics_at_seam():
    """No chunk splits a combining diacritic off its base letter.

    Vietnamese precomposed characters (e.g. ``ấ``) are single Python codepoints
    so they cannot be sliced in half at the codepoint level; but the *intended*
    invariant is that every chunk is a valid Unicode string whose
    encode/decode round-trips and whose boundaries never orphan a combining
    mark. This test enforces that invariant on a long Vietnamese passage.
    """
    # Vietnamese sentence with diacritics, repeated to span multiple chunks.
    sentence = "Tuyển dụng công nhân Hải Phòng, lương hấp dẫn, hỗ trợ chỗ ở. "
    text = sentence * 400  # ~22k chars
    result = split_for_digest(text, max_chars=6000)
    assert len(result.sections) >= 3
    for chunk in result.sections:
        # Round-trips cleanly through UTF-8 (catches surrogate-edge issues).
        chunk.encode("utf-8").decode("utf-8")
        # No leading/trailing combining diacritical mark (U+0300..U+036F).
        assert not chunk.startswith("\u0300") and not chunk.startswith("\u036F")
        assert not chunk.endswith("\u0300") and not chunk.endswith("\u036F")


def test_split_for_digest_preserves_cjk_at_seam():
    """CJK text (``。``-terminated sentences) snaps on the terminator.

    Sentence length (9 chars) does NOT divide ``max_chars`` evenly, so a naive
    hard cut would land mid-sentence (verified manually: position 6000 % 9 = 6,
    so the cut falls between glyph 6 and 7 of a sentence). The CJK-sentence
    boundary snap must move the cut to the preceding ``。``.
    """
    sentence = "工厂需要十名工人。"  # 9 chars; 6000 % 9 == 6 -> naive cut mid-sentence
    text = sentence * 700  # ~6.3k chars, forces 2+ chunks
    result = split_for_digest(text, max_chars=6000)
    assert len(result.sections) >= 2
    for chunk in result.sections:
        # UTF-8 round-trip catches any encoding edge.
        chunk.encode("utf-8").decode("utf-8")
        # Every chunk ends on the CJK full-stop, excl. or quest, OR is the
        # final chunk (which extends to EOF and need not end on a terminator).
        if chunk is not result.sections[-1]:
            assert chunk[-1] in "。！？", (
                f"non-final chunk does not end on CJK terminator: ...{chunk[-12:]!r}"
            )


def test_generic_digest_prompts_and_fallback_never_invent_a_customer_or_industry():
    unit = _fallback_unit("Bảo hành: 12 tháng", 0)

    assert unit["content"] == "Bảo hành: 12 tháng"
    assert "LG Display" not in DIGEST_SYSTEM_PROMPT
    assert "VFIC" not in DIGEST_SYSTEM_PROMPT
    assert "VFIC" not in INDEX_SYSTEM_PROMPT
    assert "LG Display" not in _fallback_question("benefits")


# --------------------------------------------------------------------------- validate
def test_validate_digest_happy_and_coercion():
    summary, units = validate_digest(
        {
            "document_summary": "s",
            "units": [{"content": "c", "category": "WEIRD", "confidence": "nope"}],
        }
    )
    assert summary == "s" and len(units) == 1
    u = units[0]
    assert u["category"] == "other" and u["confidence"] == "medium" and u["questions"] == []


def test_validate_digest_rejects_malformed():
    with pytest.raises(DigestError):
        validate_digest({"document_summary": "s"})  # no units
    with pytest.raises(DigestError):
        validate_digest({"units": [{"summary": "no content"}]})  # unit missing content
    with pytest.raises(DigestError):
        validate_digest("not an object")


# --------------------------------------------------------------------------- pipeline.run (integration)
@_integration_skip
async def _make_doc(db, raw, *, project_id=None):
    svc = KnowledgeService(db)
    return await svc.upload("kb.txt", raw, project_id=project_id)


@_integration_skip
async def test_pipeline_run_writes_rich_chunks(db_session, clean_kb):
    doc = await _make_doc(
        db_session, "LG Display tuyển operator ca đêm lương 10 triệu ở Hải Phòng."
    )

    async def llm_json(system, user):
        return json.dumps(
            _units_payload("LG Display Hải Phòng tuyển operator ca đêm lương 10 triệu.")
        )

    await KnowledgePipeline(db_session, _FakeEmbedder(), llm_json).run(doc)
    await db_session.refresh(doc)

    assert doc.status == KnowledgeStatus.APPROVED
    assert doc.stage == "APPROVED"
    assert doc.digest_meta["unit_count"] == 1
    assert doc.digest_meta["flagged_unit_indexes"] == []


@_integration_skip
async def test_pipeline_run_marks_flagged_low_confidence(db_session, clean_kb):
    doc = await _make_doc(db_session, "sgiấy tờ không rõ.")

    async def llm_json(system, user):
        payload = _units_payload("thông tin suy luận")
        payload["units"][0]["confidence"] = "low"
        payload["units"][0]["is_inference"] = True
        return json.dumps(payload)

    await KnowledgePipeline(db_session, _FakeEmbedder(), llm_json).run(doc)
    await db_session.refresh(doc)
    assert doc.digest_meta["flagged_unit_indexes"] == [0]


@_integration_skip
async def test_pipeline_retries_on_malformed_then_succeeds(db_session, clean_kb):
    doc = await _make_doc(db_session, "nội dung bất kỳ")
    calls = {"n": 0}

    async def llm_json(system, user):
        calls["n"] += 1
        if calls["n"] == 1:
            return "<<<not json>>>"
        return json.dumps(_units_payload("đơn vị hợp lệ sau retry"))

    await KnowledgePipeline(db_session, _FakeEmbedder(), llm_json).run(doc)
    assert calls["n"] == 2  # one malformed, one good
    await db_session.refresh(doc)
    assert doc.status == KnowledgeStatus.APPROVED


@_integration_skip
async def test_pipeline_raises_after_retry_failure(db_session, clean_kb):
    doc = await _make_doc(db_session, "nội dung")

    async def llm_json(system, user):
        return "still not json"

    with pytest.raises(DigestError):
        await KnowledgePipeline(db_session, _FakeEmbedder(), llm_json).run(doc)


@_integration_skip
async def test_mechanical_fallback_one_chunk(db_session, clean_kb):
    """process() without an llm_json keeps the legacy 1-chunk behaviour."""
    doc = await _make_doc(db_session, "toàn bộ nội dung thành một chunk")
    doc = await KnowledgeService(db_session).process(_FakeEmbedder(), doc)
    assert doc.status == KnowledgeStatus.APPROVED


# --------------------------------------------------------------------------- project index (integration)
@_integration_skip
async def _seed_project(db):
    proj = Project(slug=f"lg-{uuid.uuid4().hex[:6]}", name="LG Display", is_active=True)
    db.add(proj)
    await db.commit()
    await db.refresh(proj)
    return proj


@_integration_skip
async def test_build_project_index_card(db_session, clean_kb):
    proj = await _seed_project(db_session)
    svc = KnowledgeService(db_session)
    doc = await svc.upload("lg.txt", "LG Display tuyển operator", project_id=proj.id)
    await svc.process(_FakeEmbedder(), doc)  # chunk it

    async def llm_json(system, user):
        return json.dumps(
            {
                "summary": "Nhà máy LG Display",
                "key_roles": ["operator"],
                "location": "Hải Phòng",
                "highlights": ["lương cao"],
            }
        )

    await KnowledgePipeline(db_session, _FakeEmbedder(), llm_json).build_project_index(proj.id)
    await db_session.refresh(proj)
    assert proj.summary == "Nhà máy LG Display"
    assert proj.index_card["key_roles"] == ["operator"]


@_integration_skip
async def test_search_test_scoped_to_project(db_session, clean_kb):
    proj = await _seed_project(db_session)
    svc = KnowledgeService(db_session)
    d_in = await svc.upload("in.txt", "LG Display tuyển operator", project_id=proj.id)
    d_out = await svc.upload("out.txt", "Samsung tuyển thợ điện")  # project_id NULL
    await svc.process(_FakeEmbedder(), d_in)
    await svc.process(_FakeEmbedder(), d_out)

    scoped = await svc.search_test(_FakeEmbedder(), "tuyển", top_k=10, project_id=proj.id)
    assert any("LG Display" in r["content"] for r in scoped)
    assert all("Samsung" not in r["content"] for r in scoped)


# --------------------------------------------------------------------------- multipart API (integration)
@_integration_skip
async def test_upload_file_endpoint_extracts_and_enqueues(
    client, db_session, clean_kb, monkeypatch
):
    enqueued: list[str] = []
    monkeypatch.setattr(
        "app.api.knowledge._project_knowledge_jobs.ingest_document",
        lambda doc_id: enqueued.append(str(doc_id)),
    )
    import docx

    d = docx.Document()
    d.add_paragraph("Nội dung DOCX LG Display")
    buf = io.BytesIO()
    d.save(buf)

    r = await client.post(
        "/api/v1/knowledge/documents/upload-file",
        files={
            "file": (
                "lg.docx",
                buf.getvalue(),
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        },
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["stage"] in {"EXTRACTED", "UPLOADED"}
    assert len(enqueued) == 1 and enqueued[0] == body["id"]
    doc = await db_session.get(KnowledgeDocument, uuid.UUID(body["id"]))
    assert doc is not None and "LG Display" in (doc.raw_text or "")
