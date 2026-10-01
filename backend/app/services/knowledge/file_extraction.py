"""Pure file-format detection and text extraction for knowledge uploads.

Single owner of upload format resolution. Both knowledge upload paths come
through here under one strict contract: only plain text, markdown, DOCX and
XLSX resolve, YAML is refused by name, and everything else is rejected so the
route can answer 422. Every accepted format is normalized to text before
ingest.

The DOCX and XLSX branches parse the OOXML container with the standard library
and are recorded on the stored document under those distinct provenance values
(see :func:`extraction_method_for_format`); a zip container read as UTF-8 is
mojibake, not text, so those two formats must never fall through to the
text-decode branch. Every other format is decoded as UTF-8.

No DB/ORM imports — only file-format detection and file text extraction.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import date, timedelta
from io import BytesIO
from pathlib import Path
from zipfile import BadZipFile, ZipFile
from xml.etree import ElementTree as ET

DOCX_MIME_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
XLSX_MIME_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
WORD_XML_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"

# The only formats a knowledge upload may carry, on either lane. Each one
# normalizes to ingestable text (OOXML parse or UTF-8 decode).
KB_RELEASE_FORMATS = frozenset({"docx", "xlsx", "markdown", "text"})

_MARKDOWN_CONTENT_TYPES = frozenset({"text/markdown", "text/x-markdown"})
_PLAIN_TEXT_CONTENT_TYPES = frozenset({"text/plain", *_MARKDOWN_CONTENT_TYPES})
_YAML_CONTENT_TYPES = frozenset({"application/yaml", "text/yaml"})
_YAML_SUFFIXES = frozenset({".yaml", ".yml"})


class KnowledgeFileExtractionError(ValueError):
    """Raised when an uploaded source file cannot be converted to ingestable text."""


def _detect_upload_format(
    file_name: str,
    content_type: str,
    *,
    allowed_formats: frozenset[str] | None = None,
) -> str:
    """Resolve an upload's format from its name and declared content type.

    Both lanes share one strict contract: plain text, markdown, DOCX and XLSX
    are the only accepted knowledge formats, YAML is refused by name so an old
    habit surfaces as a clear 422 instead of silently ingested markup, and
    anything else raises ``ValueError`` so the route can answer 422.
    ``allowed_formats`` narrows the accepted set for callers that want a
    subset; ``None`` means the full release set.
    """
    suffix = Path(file_name or "").suffix.lower()
    normalized_type = (content_type or "").split(";", 1)[0].strip().lower()
    if suffix in _YAML_SUFFIXES or normalized_type in _YAML_CONTENT_TYPES:
        raise ValueError("YAML knowledge files are not accepted; convert to .md or .txt.")
    if suffix == ".docx" or normalized_type == DOCX_MIME_TYPE:
        resolved = "docx"
    elif suffix == ".xlsx" or normalized_type == XLSX_MIME_TYPE:
        resolved = "xlsx"
    elif suffix in {".md", ".markdown"}:
        resolved = "markdown"
    elif suffix == ".txt":
        resolved = "text"
    elif suffix == "" and normalized_type in _PLAIN_TEXT_CONTENT_TYPES:
        resolved = "markdown" if "markdown" in normalized_type else "text"
    elif normalized_type not in _PLAIN_TEXT_CONTENT_TYPES:
        raise ValueError("Only .txt, .md, .docx and .xlsx knowledge files are supported.")
    else:
        raise ValueError("Knowledge filenames must end in .txt, .md, .docx or .xlsx.")
    if resolved not in (allowed_formats or KB_RELEASE_FORMATS):
        raise ValueError(f"Knowledge files of type {resolved} are not supported.")
    return resolved


def mime_type_for_format(file_format: str, content_type: str) -> str:
    """The MIME type recorded on a stored document for a resolved upload format."""
    if file_format == "docx":
        return DOCX_MIME_TYPE
    if file_format == "xlsx":
        return XLSX_MIME_TYPE
    normalized = (content_type or "").split(";", 1)[0].strip().lower()
    if normalized.startswith("text/"):
        return normalized
    return "text/markdown" if file_format == "markdown" else "text/plain"


def _extract_docx_text(data: bytes) -> str:
    """Extract paragraph text from a Word DOCX without adding runtime dependencies."""
    try:
        with ZipFile(BytesIO(data)) as archive:
            _validate_ooxml_archive(archive)
            document_xml = _read_ooxml_part(archive, "word/document.xml")
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


_XLSX_OFFICE_REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"

MAX_OOXML_MEMBERS = 1024
MAX_OOXML_PART_BYTES = 16 * 1024 * 1024
MAX_OOXML_EXPANDED_BYTES = 64 * 1024 * 1024
MAX_OOXML_TEXT_CHARS = 16 * 1024 * 1024
MAX_XLSX_COLUMNS = 16_384


def _validate_ooxml_archive(archive: ZipFile) -> None:
    members = archive.infolist()
    if (
        len(members) > MAX_OOXML_MEMBERS
        or sum(member.file_size for member in members) > MAX_OOXML_EXPANDED_BYTES
        or any(
            member.filename.endswith(".xml") and member.file_size > MAX_OOXML_PART_BYTES
            for member in members
        )
    ):
        raise KnowledgeFileExtractionError("Tệp Office vượt quá giới hạn xử lý nội dung.")
    if any(member.flag_bits & 1 for member in members):
        raise KnowledgeFileExtractionError("Tệp Office có mật khẩu chưa được hỗ trợ.")


def _read_ooxml_part(archive: ZipFile, name: str) -> bytes:
    # Check both the directory declaration and the actual bounded expansion.
    if archive.getinfo(name).file_size > MAX_OOXML_PART_BYTES:
        raise KnowledgeFileExtractionError("Tệp Office vượt quá giới hạn xử lý nội dung.")
    with archive.open(name) as part:
        expanded = part.read(MAX_OOXML_PART_BYTES + 1)
    if len(expanded) > MAX_OOXML_PART_BYTES:
        raise KnowledgeFileExtractionError("Tệp Office vượt quá giới hạn xử lý nội dung.")
    return expanded

# Built-in number-format ids that render a date and/or a time. The id space
# below 164 is reserved by the format itself; 164+ come from <numFmt> entries in
# xl/styles.xml, which is why _xlsx_date_styles reads that table too.
_XLSX_BUILTIN_DATE_FORMATS = frozenset({14, 15, 16, 17, 18, 19, 20, 21, 22, 45, 46, 47})


def _local_name(tag: str) -> str:
    """Strip the XML namespace from an element tag."""
    return tag.rsplit("}", 1)[-1]


def _xlsx_shared_strings(archive: ZipFile) -> list[str]:
    """The workbook's shared-string table, in ``<si>`` index order (absent -> empty)."""
    try:
        root = ET.fromstring(_read_ooxml_part(archive, "xl/sharedStrings.xml"))
    except (KeyError, ET.ParseError):
        return []
    return [
        "".join(node.text or "" for node in item.iter() if _local_name(node.tag) == "t")
        for item in root
        if _local_name(item.tag) == "si"
    ]


def _xlsx_sheet_members(archive: ZipFile) -> list[str]:
    """Worksheet zip members in workbook order, resolved through the rels part."""
    try:
        workbook = ET.fromstring(_read_ooxml_part(archive, "xl/workbook.xml"))
        rels = ET.fromstring(_read_ooxml_part(archive, "xl/_rels/workbook.xml.rels"))
    except (KeyError, ET.ParseError):
        return []
    targets = {
        rel.get("Id"): rel.get("Target") for rel in rels if _local_name(rel.tag) == "Relationship"
    }
    members: list[str] = []
    for sheet in workbook.iter():
        if _local_name(sheet.tag) != "sheet":
            continue
        rel_id = sheet.get(f"{{{_XLSX_OFFICE_REL_NS}}}id") or sheet.get("id")
        target = targets.get(rel_id or "")
        if not target:
            continue
        members.append(target.lstrip("/") if target.startswith("/") else f"xl/{target}")
        if len(members) > MAX_OOXML_MEMBERS:
            raise KnowledgeFileExtractionError("Tệp Office vượt quá giới hạn xử lý nội dung.")
    if len(set(members)) != len(members):
        raise KnowledgeFileExtractionError("XLSX có tham chiếu trang tính bị trùng.")
    return members


def _is_date_format_code(code: str) -> bool:
    """Whether a number-format code renders a date/time rather than a plain number."""
    stripped = re.sub(r"\[[^\]]*\]", "", code)
    stripped = re.sub(r'"[^"]*"', "", stripped).replace("\\", "")
    return any(marker in stripped for marker in "ymdhs")


def _xlsx_date_styles(archive: ZipFile) -> set[int]:
    """``<xf>`` indices in ``cellXfs`` that carry a date/time number format."""
    try:
        root = ET.fromstring(_read_ooxml_part(archive, "xl/styles.xml"))
    except (KeyError, ET.ParseError):
        return set()
    custom: dict[int, str] = {}
    for node in root.iter():
        if _local_name(node.tag) != "numFmt":
            continue
        try:
            custom[int(node.get("numFmtId", ""))] = node.get("formatCode", "")
        except ValueError:
            continue
    date_styles: set[int] = set()
    for group in root:
        if _local_name(group.tag) != "cellXfs":
            continue
        for index, xf in enumerate(group):
            try:
                num_fmt_id = int(xf.get("numFmtId", "0"))
            except ValueError:
                continue
            if num_fmt_id in _XLSX_BUILTIN_DATE_FORMATS or _is_date_format_code(
                custom.get(num_fmt_id, "")
            ):
                date_styles.add(index)
    return date_styles


def _xlsx_time_of_day(fraction: float) -> str:
    total = int(round(fraction * 86400)) % 86400
    return f"{total // 3600:02d}:{total % 3600 // 60:02d}:{total % 60:02d}"


def _xlsx_serial_to_text(raw: str) -> str:
    """Render a date-formatted numeric cell as ISO text instead of its serial number."""
    try:
        serial = float(raw)
    except ValueError:
        return raw
    days = int(serial)
    if days == 0:
        return _xlsx_time_of_day(serial)
    if days == 60:
        # Excel's phantom 1900-02-29: no real date maps here.
        return raw
    # Serials below 60 predate the 1900 leap-year bug Excel kept for compatibility.
    epoch = date(1899, 12, 31) if days < 60 else date(1899, 12, 30)
    rendered = (epoch + timedelta(days=days)).isoformat()
    fraction = serial - days
    return rendered if fraction == 0 else f"{rendered} {_xlsx_time_of_day(fraction)}"


def _xlsx_column_index(cell_ref: str) -> int:
    """Zero-based column index of a cell reference such as ``AB12``."""
    if not cell_ref:
        return 0
    match = re.fullmatch(r"([A-Za-z]{1,3})[1-9][0-9]*", cell_ref)
    if match is None:
        raise KnowledgeFileExtractionError("Tham chiếu cột trong XLSX không hợp lệ.")
    index = 0
    for char in match.group(1).upper():
        index = index * 26 + (ord(char) - 64)
    if index > MAX_XLSX_COLUMNS:
        raise KnowledgeFileExtractionError("Tham chiếu cột trong XLSX vượt quá giới hạn.")
    return max(index - 1, 0)


def _xlsx_cell_text(cell: ET.Element, shared: list[str], date_styles: set[int]) -> str:
    """One cell as text, resolving shared/inline strings, booleans and date serials."""
    cell_type = cell.get("t", "n")
    if cell_type == "inlineStr":
        inline = next((node for node in cell if _local_name(node.tag) == "is"), None)
        if inline is None:
            return ""
        return "".join(node.text or "" for node in inline.iter() if _local_name(node.tag) == "t")
    value = next((node for node in cell if _local_name(node.tag) == "v"), None)
    raw = (value.text or "").strip() if value is not None else ""
    if cell_type == "s":
        try:
            return shared[int(raw)]
        except (ValueError, IndexError):
            return ""
    if cell_type == "b":
        return {"0": "FALSE", "1": "TRUE"}.get(raw, "")
    style = cell.get("s")
    if style is not None and cell_type in {"n", "d"} and style.isdigit():
        if int(style) in date_styles:
            return _xlsx_serial_to_text(raw)
    return raw


def _xlsx_sheet_lines(sheet_xml: bytes, shared: list[str], date_styles: set[int]) -> list[str]:
    """One tab-separated line per non-blank row, gaps preserved by cell reference."""
    root = ET.fromstring(sheet_xml)
    lines: list[str] = []
    text_chars = 0
    for row in root.iter():
        if _local_name(row.tag) != "row":
            continue
        placed: dict[int, str] = {}
        cursor = 0
        for cell in row:
            if _local_name(cell.tag) != "c":
                continue
            column = _xlsx_column_index(cell.get("r", ""))
            placed[column] = _xlsx_cell_text(cell, shared, date_styles)
            cursor = max(cursor, column)
        cells = [placed.get(index, "") for index in range(cursor + 1)]
        # A shared string can be referenced thousands of times by tiny XML.
        # Budget the projected row before join allocates its expanded text.
        row_chars = sum(len(cell) for cell in cells) + max(len(cells) - 1, 0)
        text_chars += row_chars + 1
        if text_chars > MAX_OOXML_TEXT_CHARS:
            raise KnowledgeFileExtractionError("Tệp Office vượt quá giới hạn xử lý nội dung.")
        if any(cell.strip() for cell in cells):
            lines.append("\t".join(cells))
    return lines


def _extract_xlsx_text(data: bytes) -> str:
    """Flatten an XLSX workbook to tab-separated rows (one row per line).

    Parsed from the OOXML parts with the stdlib, for the same reason
    :func:`_extract_docx_text` is: the legacy upload path accepts a real .xlsx,
    and reading a zip container as UTF-8 yields mojibake rather than text, so
    this branch has to actually understand the workbook. Doing it here rather
    than through a spreadsheet library keeps the declared dependency set — and
    therefore the image — unchanged.
    """
    try:
        with ZipFile(BytesIO(data)) as archive:
            _validate_ooxml_archive(archive)
            shared = _xlsx_shared_strings(archive)
            date_styles = _xlsx_date_styles(archive)
            members = _xlsx_sheet_members(archive) or sorted(
                name
                for name in archive.namelist()
                if name.startswith("xl/worksheets/") and name.endswith(".xml")
            )
            lines: list[str] = []
            text_chars = 0
            for member in members:
                try:
                    sheet_xml = _read_ooxml_part(archive, member)
                except KeyError:
                    continue
                sheet_lines = _xlsx_sheet_lines(sheet_xml, shared, date_styles)
                text_chars += sum(len(line) + 1 for line in sheet_lines)
                if text_chars > MAX_OOXML_TEXT_CHARS:
                    raise KnowledgeFileExtractionError("Tệp Office vượt quá giới hạn xử lý nội dung.")
                lines.extend(sheet_lines)
    except BadZipFile as exc:
        raise KnowledgeFileExtractionError("XLSX không hợp lệ hoặc không đọc được.") from exc
    except ET.ParseError as exc:
        raise KnowledgeFileExtractionError("Không đọc được nội dung XML trong XLSX.") from exc
    return "\n".join(lines)


# The parsed (non-text) formats, and the provenance value each one records. The
# recorded `extraction` on a stored document names the mechanism that ACTUALLY
# produced its text, so this table is the single source of truth: `extract_text`
# dispatches through it and `extraction_method_for_format` reads it, rather than
# each side keeping its own list that can silently drift apart.
_PARSED_FORMAT_METHODS: dict[str, str] = {
    "docx": "word_ooxml",
    "xlsx": "spreadsheet_ooxml",
}

_PARSED_FORMAT_EXTRACTORS: dict[str, Callable[[bytes], str]] = {
    "docx": _extract_docx_text,
    "xlsx": _extract_xlsx_text,
}


def extraction_method_for_format(file_format: str) -> str:
    """The provenance value naming how text for ``file_format`` is actually produced."""
    return _PARSED_FORMAT_METHODS.get(file_format, "utf8_decode")


def is_parsed_format(file_format: str) -> bool:
    """Whether the format is structurally parsed rather than decoded as UTF-8 text."""
    return file_format in _PARSED_FORMAT_EXTRACTORS


def extract_text(
    file_name: str,
    content_type: str,
    data: bytes | str,
    *,
    allowed_formats: frozenset[str] | None = None,
    decode_errors: str = "strict",
) -> str:
    """Convert an uploaded source file to ingestable plain text.

    Dispatches by detected format: DOCX and XLSX are parsed as OOXML containers;
    plain text and markdown are decoded as UTF-8. Raises
    ``KnowledgeFileExtractionError`` on a structurally invalid binary file; an
    undecodable text file surfaces its ``UnicodeDecodeError`` to the caller
    (upload handler) as a hard failure unless the caller asks for
    ``decode_errors="replace"``.

    ``allowed_formats`` narrows resolution to the strict KB-release contract (see
    :func:`_detect_upload_format`); ``decode_errors`` selects the text-decode
    policy for everything that is not a parsed binary format.
    """
    if isinstance(data, str):
        return data
    fmt = _detect_upload_format(file_name, content_type, allowed_formats=allowed_formats)
    parsed = _PARSED_FORMAT_EXTRACTORS.get(fmt)
    if parsed is not None:
        return parsed(data)
    return data.decode("utf-8", errors=decode_errors)
