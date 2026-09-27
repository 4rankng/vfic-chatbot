"""The two knowledge-upload format contracts, both owned by ``file_extraction``.

ARCH-22 collapsed three diverged extraction paths into one owner. The two
endpoints deliberately resolve formats differently and must keep doing so:

* the legacy document upload (``upload_bytes``) resolves permissively — any
  suffix / content type is ingested, text decoded as UTF-8 with replacement;
* the KB-version release upload (``upload_text_file``) resolves strictly —
  only .docx / .md / .txt resolve, anything else is a ``ValueError`` the route
  maps to 422.

These tests pin the *behavior* at both boundaries, so a future "unify the
detectors" change cannot silently widen or narrow either endpoint.

The provenance block (``source_file.extraction``) is pinned alongside the text
it describes, because the two are one fact: a document that records
``utf8_decode`` while its text actually came out of an OOXML parse is lying
about its own origin, and downstream audit reads that field as fact.
"""

from __future__ import annotations

import io
from xml.sax.saxutils import escape
from zipfile import ZipFile

import pytest

from app.services.knowledge.file_extraction import (
    KB_RELEASE_FORMATS,
    KnowledgeFileExtractionError,
    _detect_upload_format,
    extraction_method_for_format,
    extract_text,
    is_parsed_format,
    mime_type_for_format,
)
from app.services.knowledge.service import KnowledgeService

DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
_SSML = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"


def _xlsx_bytes(rows: list[list[tuple[str, str] | None]], *, date_style_index: int = 1) -> bytes:
    """Build a real XLSX (an OOXML zip) with the given rows.

    Each cell is ``(kind, value)``; ``None`` is a gap the reader must still
    leave a column for, so tab alignment is asserted rather than assumed.
    ``"s"`` is a shared-string cell, ``"n"`` a numeric one (which gets
    ``date_style_index`` so date rendering can be exercised), anything else an
    inline string.
    """
    shared: list[str] = []
    sheet_rows: list[str] = []
    for row_number, row in enumerate(rows, start=1):
        cells: list[str] = []
        for column, cell in enumerate(row):
            reference = f"{chr(ord('A') + column)}{row_number}"
            if cell is None:
                # A blank cell is still a <c> element, or the reader cannot know
                # the column exists and every later value shifts left.
                cells.append(f'<c r="{reference}"/>')
                continue
            kind, value = cell
            if kind == "s":
                if value not in shared:
                    shared.append(value)
                cells.append(f'<c r="{reference}" t="s"><v>{shared.index(value)}</v></c>')
            elif kind == "n":
                cells.append(f'<c r="{reference}" s="{date_style_index}"><v>{value}</v></c>')
            else:
                cells.append(
                    f'<c r="{reference}" t="inlineStr"><is><t>{escape(value)}</t></is></c>'
                )
        sheet_rows.append(f"<row>{''.join(cells)}</row>")
    buffer = io.BytesIO()
    with ZipFile(buffer, "w") as archive:
        archive.writestr(
            "xl/workbook.xml",
            f'<workbook xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'
            f' xmlns="{_SSML}"><sheets><sheet name="Sheet1" sheetId="1" r:id="rId1"/></sheets></workbook>',
        )
        archive.writestr(
            "xl/_rels/workbook.xml.rels",
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Target="worksheets/sheet1.xml"/></Relationships>',
        )
        archive.writestr(
            "xl/sharedStrings.xml",
            f'<sst xmlns="{_SSML}" count="{len(shared)}" uniqueCount="{len(shared)}">'
            + "".join(f"<si><t>{escape(value)}</t></si>" for value in shared)
            + "</sst>",
        )
        archive.writestr(
            "xl/styles.xml",
            f'<styleSheet xmlns="{_SSML}"><cellXfs><xf numFmtId="0"/><xf numFmtId="14"/></cellXfs>'
            "</styleSheet>",
        )
        archive.writestr(
            "xl/worksheets/sheet1.xml",
            f'<worksheet xmlns="{_SSML}"><sheetData>{"".join(sheet_rows)}</sheetData></worksheet>',
        )
    return buffer.getvalue()


def _docx_bytes(*paragraphs: str) -> bytes:
    body = "".join(f"<w:p><w:r><w:t>{escape(p)}</w:t></w:r></w:p>" for p in paragraphs)
    document_xml = (
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f"<w:body>{body}</w:body></w:document>"
    )
    buffer = io.BytesIO()
    with ZipFile(buffer, "w") as archive:
        archive.writestr("word/document.xml", document_xml)
    return buffer.getvalue()


def _release(file_name: str, content_type: str) -> str:
    return _detect_upload_format(file_name, content_type, allowed_formats=KB_RELEASE_FORMATS)


def _legacy(file_name: str, content_type: str) -> str:
    return _detect_upload_format(file_name, content_type)


def test_the_legacy_upload_ingests_a_csv_the_release_upload_refuses() -> None:
    # The asymmetry is the contract: the legacy document upload accepts a
    # spreadsheet/csv, the KB-version release upload does not.
    assert _legacy("a.csv", "text/csv") == "text"
    with pytest.raises(ValueError):
        _release("a.csv", "text/csv")


@pytest.mark.parametrize(
    ("file_name", "content_type"),
    [
        ("a.pdf", "application/pdf"),
        ("a.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
        ("a.doc", "application/msword"),
    ],
)
def test_the_release_upload_refuses_every_non_text_format(file_name, content_type) -> None:
    with pytest.raises(ValueError, match="Only .txt and .md knowledge files are supported."):
        _release(file_name, content_type)


def test_a_csv_declared_as_plain_text_is_refused_for_its_suffix() -> None:
    # A wrong-but-plausible Content-Type must not smuggle a .csv past the
    # release contract: the suffix is checked, so this is the other error.
    with pytest.raises(ValueError, match="Knowledge filenames must end in .txt or .md."):
        _release("a.csv", "text/plain")


@pytest.mark.parametrize(
    ("file_name", "content_type", "expected"),
    [
        ("tuyen-dung.docx", DOCX_MIME, "docx"),
        ("kb.md", "text/markdown", "markdown"),
        ("kb.txt", "text/plain", "text"),
        ("kb.md", "application/octet-stream", "markdown"),
        ("release", "text/plain", "text"),
        ("release", "text/markdown", "markdown"),
    ],
)
def test_the_release_upload_accepts_docx_markdown_and_text(
    file_name, content_type, expected
) -> None:
    assert _release(file_name, content_type) == expected


def test_the_release_upload_refuses_a_format_outside_the_allowed_set() -> None:
    # ``allowed_formats`` is the whole extension point: a caller that does not
    # want DOCX in a release file says so, rather than re-implementing a detector.
    with pytest.raises(ValueError, match="not supported"):
        _detect_upload_format("a.docx", DOCX_MIME, allowed_formats=frozenset({"markdown", "text"}))


def test_a_release_upload_replaces_undecodable_bytes_instead_of_failing() -> None:
    # The release path decodes with replacement: a stray byte in an otherwise
    # valid .md must not turn the whole upload into a 500.
    assert (
        extract_text(
            "kb.md",
            "text/markdown",
            b"n\xf8i dung",
            allowed_formats=KB_RELEASE_FORMATS,
            decode_errors="replace",
        )
        == "n�i dung"
    )


def test_the_default_decode_still_fails_loudly_on_undecodable_bytes() -> None:
    # The permissive default is unchanged: a caller that does not opt into
    # replacement gets the UnicodeDecodeError.
    with pytest.raises(UnicodeDecodeError):
        extract_text("kb.md", "text/markdown", b"n\xf8i dung")


def test_the_legacy_upload_records_the_extraction_it_actually_used() -> None:
    text, source_metadata = KnowledgeService._extract_upload_text(
        "tuyen-dung.docx", DOCX_MIME, _docx_bytes("Yêu cầu có xe đưa đón")
    )

    assert "xe đưa đón" in text
    assert source_metadata == {
        "format": "docx",
        "mime_type": DOCX_MIME,
        "extraction": "word_ooxml",
        "text_checksum": source_metadata["text_checksum"],
    }
    assert source_metadata["text_checksum"].startswith("sha256:")


def test_the_legacy_upload_replaces_undecodable_bytes_in_a_text_upload() -> None:
    text, source_metadata = KnowledgeService._extract_upload_text(
        "notes.csv", "text/csv", b"ten,l\xe9u"
    )

    assert "l�u" in text
    assert source_metadata["format"] == "text"
    assert source_metadata["extraction"] == "utf8_decode"


def test_a_docx_without_any_text_is_refused_on_the_legacy_path() -> None:
    with pytest.raises(KnowledgeFileExtractionError):
        KnowledgeService._extract_upload_text("rong.docx", DOCX_MIME, _docx_bytes("   "))


def test_the_extraction_error_is_a_value_error_so_both_routes_answer_422() -> None:
    # The KB route catches ValueError; the legacy route catches
    # KnowledgeFileExtractionError. One class satisfies both contracts.
    assert issubclass(KnowledgeFileExtractionError, ValueError)


def test_a_stored_document_records_the_mime_type_of_its_resolved_format() -> None:
    assert mime_type_for_format("docx", "") == DOCX_MIME
    assert mime_type_for_format("markdown", "") == "text/markdown"
    assert mime_type_for_format("markdown", "text/plain; charset=utf-8") == "text/plain"
    assert mime_type_for_format("text", "") == "text/plain"


def test_a_legacy_xlsx_yields_real_cell_text_not_the_zip_read_as_utf8() -> None:
    # A .xlsx on the permissive legacy path is a real workbook. Decoding its zip
    # bytes as UTF-8 cannot produce "operator"/"9000000" — the assertion below is
    # therefore falsifiable by any reintroduction of the raw text-decode branch.
    data = _xlsx_bytes(
        [
            [("s", "vị trí"), ("s", "lương")],
            [("s", "operator"), ("s", "9000000")],
        ]
    )

    text, source_metadata = KnowledgeService._extract_upload_text("bang.xlsx", XLSX_MIME, data)

    assert text.splitlines() == ["vị trí\tlương", "operator\t9000000"]
    assert "PK" not in text


def test_a_legacy_xlsx_records_the_ooxml_parser_not_the_utf8_decoder() -> None:
    # The provenance must name the mechanism that actually produced the text.
    # This is the exact regression: the xlsx branch parsed the workbook while the
    # document still advertised "utf8_decode".
    _, source_metadata = KnowledgeService._extract_upload_text(
        "bang.xlsx",
        XLSX_MIME,
        _xlsx_bytes([[("s", "operator"), ("s", "9000000")]]),
    )

    assert source_metadata["extraction"] != "utf8_decode"
    assert source_metadata["extraction"] == extraction_method_for_format("xlsx")
    assert source_metadata["format"] == "xlsx"


def test_a_legacy_xlsx_keeps_empty_cell_columns_so_ingested_rows_stay_aligned() -> None:
    # A blank cell must still occupy its column: the sheet is flattened to
    # tab-separated rows, so a dropped gap silently shifts every later value
    # one column left in the chunk that gets embedded.
    text, source_metadata = KnowledgeService._extract_upload_text(
        "bang.xlsx", XLSX_MIME, _xlsx_bytes([[("s", "operator"), None, ("s", "9000000")]])
    )

    assert text == "operator\t\t9000000"
    assert source_metadata["extraction"] == "spreadsheet_ooxml"


def test_a_date_formatted_cell_is_ingested_as_a_date_not_a_serial_number() -> None:
    # Style index 1 carries numFmtId 14 (m/d/yy) in the fixture, so serial 45292
    # is 2024-01-01. Emitting "45292" would be unreadable to the candidate-facing
    # search that chunks this text.
    data = _xlsx_bytes([[("inlineStr", "ngày áp dụng")], [("n", "45292")]])

    text = extract_text("bang.xlsx", XLSX_MIME, data)

    assert "2024-01-01" in text
    assert "45292" not in text


def test_a_structurally_broken_xlsx_is_refused_rather_than_ingested_as_noise() -> None:
    # Not a zip at all: the permissive legacy path must not fall back to a raw
    # UTF-8 decode, which would happily ingest binary garbage as a document.
    with pytest.raises(KnowledgeFileExtractionError):
        KnowledgeService._extract_upload_text("bang.xlsx", XLSX_MIME, b"this is not a workbook")


@pytest.mark.parametrize(
    ("file_name", "content_type", "expected_method"),
    [
        ("notes.txt", "text/plain", "utf8_decode"),
        ("notes.md", "text/markdown", "utf8_decode"),
        ("notes.csv", "text/csv", "utf8_decode"),
    ],
)
def test_a_plain_text_upload_records_utf8_decode_because_that_is_what_decoded_it(
    file_name: str, content_type: str, expected_method: str
) -> None:
    # The counterweight to the xlsx test: not every format is parsed, and the
    # text formats must keep naming the decoder that really ran.
    text, source_metadata = KnowledgeService._extract_upload_text(
        file_name, content_type, "giá 9000000".encode()
    )

    assert text == "giá 9000000"
    assert source_metadata["extraction"] == expected_method


def test_a_legacy_docx_records_the_ooxml_parser_and_its_own_paragraph_text() -> None:
    text, source_metadata = KnowledgeService._extract_upload_text(
        "tuyen-dung.docx", DOCX_MIME, _docx_bytes("Yêu cầu có xe đưa đón")
    )

    assert text == "Yêu cầu có xe đưa đón"
    assert source_metadata["extraction"] == extraction_method_for_format("docx")
    assert source_metadata["extraction"] != "utf8_decode"


@pytest.mark.parametrize("file_format", ["docx", "xlsx"])
def test_every_parsed_format_names_a_non_utf8_mechanism(file_format: str) -> None:
    # The drift guard. A format that is structurally parsed must never be
    # recorded as a UTF-8 decode, and a format that is only decoded must be.
    assert is_parsed_format(file_format) is (
        extraction_method_for_format(file_format) != "utf8_decode"
    )


@pytest.mark.parametrize("file_format", ["text", "markdown", "csv", "json", "binary"])
def test_every_decoded_format_names_the_utf8_decoder(file_format: str) -> None:
    assert is_parsed_format(file_format) is False
    assert extraction_method_for_format(file_format) == "utf8_decode"


def test_the_two_parsed_formats_never_collide_on_one_provenance_value() -> None:
    # Distinct mechanisms must stay distinguishable in the stored metadata,
    # otherwise an audit cannot tell a Word parse from a spreadsheet parse.
    assert extraction_method_for_format("docx") != extraction_method_for_format("xlsx")


def test_the_release_upload_records_the_parser_that_produced_a_docx() -> None:
    # The release path resolves formats strictly but ran the same extractor, so
    # its provenance has to name that mechanism too rather than omit it.
    assert (
        extraction_method_for_format(
            _detect_upload_format("kb.docx", DOCX_MIME, allowed_formats=KB_RELEASE_FORMATS)
        )
        == "word_ooxml"
    )
