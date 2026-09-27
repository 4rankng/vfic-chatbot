"""Pure file-format detection and text extraction for knowledge uploads.

Single owner of upload format resolution. Both knowledge upload paths come
through here: the legacy document upload resolves permissively (any suffix /
content type, everything else decoded as UTF-8 text), while a KB-version
release file resolves strictly via ``allowed_formats`` — only the release
formats are accepted and everything else is rejected.

No DB/ORM imports — only file-format detection and file text extraction.
"""

from __future__ import annotations

from io import BytesIO
from pathlib import Path
from zipfile import BadZipFile, ZipFile
from xml.etree import ElementTree as ET

DOCX_MIME_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
WORD_XML_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"

# The only formats a KB-version release file may carry.
KB_RELEASE_FORMATS = frozenset({"docx", "markdown", "text"})

_MARKDOWN_CONTENT_TYPES = frozenset({"text/markdown", "text/x-markdown"})
_PLAIN_TEXT_CONTENT_TYPES = frozenset({"text/plain", *_MARKDOWN_CONTENT_TYPES})


class KnowledgeFileExtractionError(ValueError):
    """Raised when an uploaded source file cannot be converted to ingestable text."""


def _detect_upload_format(
    file_name: str,
    content_type: str,
    *,
    allowed_formats: frozenset[str] | None = None,
) -> str:
    """Resolve an upload's format from its name and declared content type.

    Without ``allowed_formats`` the resolution is permissive: a known suffix or
    content type wins, anything else falls back to the raw suffix, then the raw
    content type, then ``"binary"``. This is the legacy document-upload contract.

    With ``allowed_formats`` the resolution is strict: only the KB release
    formats (.docx, .md, .txt — plus a suffixed-less ``text/*`` body) resolve,
    and anything else raises ``ValueError`` so the route can answer 422. This
    is the KB-version release contract; the same files are not interchangeable
    between the two endpoints.
    """
    suffix = Path(file_name or "").suffix.lower()
    normalized_type = (content_type or "").split(";", 1)[0].strip().lower()
    if allowed_formats is None:
        if suffix == ".docx" or normalized_type == DOCX_MIME_TYPE:
            return "docx"
        if suffix == ".md" or normalized_type in _MARKDOWN_CONTENT_TYPES:
            return "markdown"
        if suffix == ".txt" or normalized_type.startswith("text/"):
            return "text"
        return suffix.removeprefix(".") or normalized_type or "binary"
    if suffix == ".docx" or normalized_type == DOCX_MIME_TYPE:
        resolved = "docx"
    elif suffix == ".md":
        resolved = "markdown"
    elif suffix == ".txt":
        resolved = "text"
    elif suffix == "" and normalized_type in _PLAIN_TEXT_CONTENT_TYPES:
        resolved = "markdown" if "markdown" in normalized_type else "text"
    elif normalized_type not in _PLAIN_TEXT_CONTENT_TYPES:
        raise ValueError("Only .txt and .md knowledge files are supported.")
    else:
        raise ValueError("Knowledge filenames must end in .txt or .md.")
    if resolved not in allowed_formats:
        raise ValueError(f"Knowledge files of type {resolved} are not supported.")
    return resolved


def mime_type_for_format(file_format: str, content_type: str) -> str:
    """The MIME type recorded on a stored document for a resolved upload format."""
    if file_format == "docx":
        return DOCX_MIME_TYPE
    normalized = (content_type or "").split(";", 1)[0].strip().lower()
    if normalized.startswith("text/"):
        return normalized
    return "text/markdown" if file_format == "markdown" else "text/plain"


def _extract_docx_text(data: bytes) -> str:
    """Extract paragraph text from a Word DOCX without adding runtime dependencies."""
    try:
        with ZipFile(BytesIO(data)) as archive:
            document_xml = archive.read("word/document.xml")
    except (BadZipFile, KeyError) as exc:
        raise KnowledgeFileExtractionError("DOCX không hợp lệ hoặc thiếu nội dung Word.") from exc

    try:
        root = ET.fromstring(document_xml)
    except ET.ParseError as exc:
        raise KnowledgeFileExtractionError("Không đọc được nội dung XML trong DOCX.") from exc

    paragraphs: list[str] = []
    for paragraph in root.iter(f"{WORD_XML_NS}p"):
        parts: list[str] = []
        for node in paragraph.iter():
            if node.tag == f"{WORD_XML_NS}t" and node.text:
                parts.append(node.text)
            elif node.tag == f"{WORD_XML_NS}tab":
                parts.append("\t")
            elif node.tag in {f"{WORD_XML_NS}br", f"{WORD_XML_NS}cr"}:
                parts.append("\n")
        text = "".join(parts).strip()
        if text:
            paragraphs.append(text)

    return "\n\n".join(paragraphs)


def _extract_xlsx_text(data: bytes) -> str:
    """Flatten an XLSX workbook to tab-separated rows (one row per line)."""
    from openpyxl import load_workbook

    try:
        wb = load_workbook(BytesIO(data), read_only=True, data_only=True)
    except Exception as exc:  # noqa: BLE001 — openpyxl raises several concrete types
        raise KnowledgeFileExtractionError("XLSX không hợp lệ hoặc không đọc được.") from exc
    try:
        lines: list[str] = []
        for ws in wb.worksheets:
            for row in ws.iter_rows(values_only=True):
                cells = ["" if cell is None else str(cell) for cell in row]
                if any(cell.strip() for cell in cells):
                    lines.append("\t".join(cells))
    finally:
        wb.close()
    return "\n".join(lines)


def extract_text(
    file_name: str,
    content_type: str,
    data: bytes | str,
    *,
    allowed_formats: frozenset[str] | None = None,
    decode_errors: str = "strict",
) -> str:
    """Convert an uploaded source file to ingestable plain text.

    Dispatches by detected format: DOCX and XLSX are parsed; everything text-like
    (txt, md, csv, JSON, …) is decoded as UTF-8. Raises ``KnowledgeFileExtractionError``
    on a structurally invalid binary file; an undecodable text file surfaces its
    ``UnicodeDecodeError`` to the caller (upload handler) as a hard failure unless
    the caller asks for ``decode_errors="replace"``.

    ``allowed_formats`` narrows resolution to the strict KB-release contract (see
    :func:`_detect_upload_format`); ``decode_errors`` selects the text-decode
    policy for everything that is not a parsed binary format.
    """
    if isinstance(data, str):
        return data
    fmt = _detect_upload_format(file_name, content_type, allowed_formats=allowed_formats)
    if fmt == "docx":
        return _extract_docx_text(data)
    if fmt == "xlsx":
        return _extract_xlsx_text(data)
    return data.decode("utf-8", errors=decode_errors)
