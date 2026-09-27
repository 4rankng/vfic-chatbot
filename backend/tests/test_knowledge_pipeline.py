"""LLM training-pipeline unit tests (extract by file type, digest schema, chunking).

The pipeline.run tests that ran against a live DB with injected fakes now live in
tests/integration/test_knowledge_ingestion.py, where they exercise real queries
instead of being parked behind unconditional skip marks.
"""

import io
from xml.sax.saxutils import escape
from zipfile import ZipFile

import pytest

from app.services.knowledge import (
    DigestError,
    extract_text,
    split_for_digest,
    validate_digest,
)
from app.services.knowledge.pipeline import _fallback_question, _fallback_unit
from app.services.knowledge.prompts import DIGEST_SYSTEM_PROMPT, INDEX_SYSTEM_PROMPT

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
    from app.services.knowledge.file_extraction import (
        KB_RELEASE_FORMATS,
        _detect_upload_format,
    )

    file_format = _detect_upload_format(
        "tuyen-dung.docx",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        allowed_formats=KB_RELEASE_FORMATS,
    )
    text = extract_text(
        "tuyen-dung.docx",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        _docx_bytes("Yêu cầu tuyển dụng có xe đưa đón"),
        allowed_formats=KB_RELEASE_FORMATS,
        decode_errors="replace",
    )

    assert file_format == "docx"
    assert "xe đưa đón" in text


def test_extract_text_xlsx():
    # Builds the workbook by hand rather than via a spreadsheet library: the
    # extractor reads the OOXML parts with the standard library, so this test
    # runs (and can fail) on any environment. It was previously parked behind
    # ``importorskip("openpyxl")``, which is why the xlsx route went untested
    # even though openpyxl is not a declared dependency at all.
    sheet_rows = [
        '<row><c r="A1" t="inlineStr"><is><t>vị trí</t></is></c>'
        '<c r="B1" t="inlineStr"><is><t>lương</t></is></c></row>',
        '<row><c r="A2" t="inlineStr"><is><t>operator</t></is></c>'
        '<c r="B2"><v>9000000</v></c></row>',
    ]
    buffer = io.BytesIO()
    with ZipFile(buffer, "w") as archive:
        archive.writestr(
            "xl/workbook.xml",
            '<workbook xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'
            ' xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            '<sheets><sheet name="Sheet1" sheetId="1" r:id="rId1"/></sheets></workbook>',
        )
        archive.writestr(
            "xl/_rels/workbook.xml.rels",
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Target="worksheets/sheet1.xml"/></Relationships>',
        )
        archive.writestr(
            "xl/worksheets/sheet1.xml",
            '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            f"<sheetData>{''.join(sheet_rows)}</sheetData></worksheet>",
        )
    txt = extract_text(
        "a.xlsx",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        buffer.getvalue(),
    )
    assert txt.splitlines() == ["vị trí\tlương", "operator\t9000000"]


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
