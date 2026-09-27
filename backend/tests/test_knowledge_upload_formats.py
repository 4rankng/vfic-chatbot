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
    extract_text,
    mime_type_for_format,
)
from app.services.knowledge.service import KnowledgeService

DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


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
