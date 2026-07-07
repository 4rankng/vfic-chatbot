"""Pure file-format detection and DOCX text extraction for knowledge uploads.

No DB/ORM imports — only file-format detection and DOCX text extraction.
"""

from __future__ import annotations

from io import BytesIO
from pathlib import Path
from zipfile import BadZipFile, ZipFile
from xml.etree import ElementTree as ET

DOCX_MIME_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
WORD_XML_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


class KnowledgeFileExtractionError(ValueError):
    """Raised when an uploaded source file cannot be converted to ingestable text."""


def _detect_upload_format(file_name: str, content_type: str) -> str:
    suffix = Path(file_name or "").suffix.lower()
    normalized_type = (content_type or "").split(";", 1)[0].strip().lower()
    if suffix == ".docx" or normalized_type == DOCX_MIME_TYPE:
        return "docx"
    if suffix == ".md" or normalized_type in {"text/markdown", "text/x-markdown"}:
        return "markdown"
    if suffix == ".txt" or normalized_type.startswith("text/"):
        return "text"
    return suffix.removeprefix(".") or normalized_type or "binary"


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


def extract_text(file_name: str, content_type: str, data: bytes | str) -> str:
    """Convert an uploaded source file to ingestable plain text.

    Dispatches by detected format: DOCX and XLSX are parsed; everything text-like
    (txt, md, csv, JSON, …) is decoded as UTF-8. Raises ``KnowledgeFileExtractionError``
    on a structurally invalid binary file; an undecodable text file surfaces its
    ``UnicodeDecodeError`` to the caller (upload handler) as a hard failure.
    """
    if isinstance(data, str):
        return data
    fmt = _detect_upload_format(file_name, content_type)
    if fmt == "docx":
        return _extract_docx_text(data)
    if fmt == "xlsx":
        return _extract_xlsx_text(data)
    return data.decode("utf-8")
