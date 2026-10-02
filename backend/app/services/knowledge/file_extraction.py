"""Pure file-format detection and text extraction for knowledge uploads.

Single owner of upload format resolution. Both knowledge upload paths come
through here under one strict contract: plain-text documents, markdown, DOCX
and XLSX resolve, YAML is refused by name, and binary formats are rejected so the
route can answer 422. Every accepted format is normalized to text before
ingest.

The DOCX and XLSX branches parse the OOXML container with the standard library
and are recorded on the stored document under those distinct provenance values
(see :func:`extraction_method_for_format`); a zip container read as UTF-8 is
mojibake, not text, so those two formats must never fall through to the
text-decode branch. Text is decoded strictly using a Unicode BOM, an explicitly
declared supported charset, or UTF-8. Unknown encodings are never guessed.

No DB/ORM imports — only file-format detection and file text extraction.
"""

from __future__ import annotations

import codecs
import re
from collections.abc import Callable
from datetime import date, timedelta
from email.message import Message
from io import BytesIO
from pathlib import Path
from zipfile import BadZipFile, ZipFile
from xml.etree import ElementTree as ET

DOCX_MIME_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
XLSX_MIME_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
WORD_XML_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"

# The only formats a knowledge upload may carry, on either lane. Each one
# normalizes to ingestable text (OOXML parse or strict text decode).
KB_RELEASE_FORMATS = frozenset({"docx", "xlsx", "markdown", "text"})

_MARKDOWN_CONTENT_TYPES = frozenset({"text/markdown", "text/x-markdown"})
_PLAIN_TEXT_CONTENT_TYPES = frozenset(
    {
        "text/plain",
        "text/csv",
        "text/tab-separated-values",
        "application/json",
        *_MARKDOWN_CONTENT_TYPES,
    }
)
_PLAIN_TEXT_SUFFIXES = frozenset({".txt", ".text", ".csv", ".tsv", ".log", ".json", ".rst"})
_SUPPORTED_TEXT_ENCODINGS = frozenset(
    {
        "utf-8",
        "utf-8-sig",
        "utf-16",
        "utf-16-le",
        "utf-16-be",
        "utf-32",
        "utf-32-le",
        "utf-32-be",
        "ascii",
        "cp1258",
        "cp1252",
        "iso8859-1",
    }
)
_BINARY_SIGNATURES = (
    b"%PDF-",
    b"PK\x03\x04",
    b"PK\x05\x06",
    b"\x89PNG",
    b"GIF87a",
    b"GIF89a",
    b"\x1f\x8b",
    b"\x7fELF",
    b"\xd0\xcf\x11\xe0",
)
_BINARY_ASCII_SIGNATURES = tuple(
    signature.decode("ascii") for signature in _BINARY_SIGNATURES if signature.isascii()
)
_INVALID_TEXT_CHARACTERS = re.compile(r"[\x00-\x08\x0b\x0e-\x1f\x7f-\x84\x86-\x9f\ud800-\udfff]")
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
    are the only accepted knowledge formats. Common textual suffixes such as
    CSV and JSON still produce plain text, never category-schema parsing.
    YAML is refused by name so an old
    habit surfaces as a clear 422 instead of silently ingested markup, and
    anything else raises ``ValueError`` so the route can answer 422.
    ``allowed_formats`` narrows the accepted set for callers that want a
    subset; ``None`` means the full release set.
    """
    if not (file_name or "").strip():
        raise ValueError("Knowledge filenames must not be empty.")
    suffix = Path(file_name).suffix.lower()
    normalized_type = (content_type or "").split(";", 1)[0].strip().lower()
    if suffix in _YAML_SUFFIXES or normalized_type in _YAML_CONTENT_TYPES:
        raise ValueError("YAML knowledge files are not accepted; convert to .md or .txt.")
    if suffix == ".docx" or normalized_type == DOCX_MIME_TYPE:
        resolved = "docx"
    elif suffix == ".xlsx" or normalized_type == XLSX_MIME_TYPE:
        resolved = "xlsx"
    elif suffix in {".md", ".markdown"}:
        resolved = "markdown"
    elif suffix in _PLAIN_TEXT_SUFFIXES:
        resolved = "text"
    elif suffix == "" and normalized_type in _PLAIN_TEXT_CONTENT_TYPES:
        resolved = "markdown" if "markdown" in normalized_type else "text"
    elif normalized_type not in _PLAIN_TEXT_CONTENT_TYPES:
        raise ValueError(
            "Only text files (.txt, .text, .md, .markdown, .csv, .tsv, .log, .json, .rst), "
            ".docx and .xlsx knowledge files are supported."
        )
    else:
        raise ValueError("Knowledge filenames must end in a supported text, .docx or .xlsx suffix.")
    if resolved not in (KB_RELEASE_FORMATS if allowed_formats is None else allowed_formats):
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
                    raise KnowledgeFileExtractionError(
                        "Tệp Office vượt quá giới hạn xử lý nội dung."
                    )
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


def _text_encoding(data: bytes, content_type: str) -> str:
    # UTF-32 LE starts with the UTF-16 LE marker: test the longer BOM first.
    for marker, encoding in (
        (codecs.BOM_UTF32_LE, "utf-32"),
        (codecs.BOM_UTF32_BE, "utf-32"),
        (codecs.BOM_UTF16_LE, "utf-16"),
        (codecs.BOM_UTF16_BE, "utf-16"),
        (codecs.BOM_UTF8, "utf-8-sig"),
    ):
        if data.startswith(marker):
            return encoding
    declared = Message()
    declared["content-type"] = content_type or "text/plain"
    charset = declared.get_content_charset()
    if not charset:
        return "utf-8"
    try:
        encoding = codecs.lookup(charset).name
    except (LookupError, ValueError) as exc:
        raise KnowledgeFileExtractionError(
            "Mã hóa văn bản chưa được hỗ trợ. Hãy lưu tệp dưới dạng UTF-8."
        ) from exc
    if encoding not in _SUPPORTED_TEXT_ENCODINGS:
        raise KnowledgeFileExtractionError(
            "Mã hóa văn bản chưa được hỗ trợ. Hãy lưu tệp dưới dạng UTF-8."
        )
    return encoding


def _validate_text(text: str) -> str:
    if _INVALID_TEXT_CHARACTERS.search(text) or text.startswith(_BINARY_ASCII_SIGNATURES):
        raise KnowledgeFileExtractionError(
            "Tệp chứa dữ liệu nhị phân hoặc ký tự điều khiển không hợp lệ. "
            "Hãy xuất nội dung thành tệp văn bản UTF-8."
        )
    if not text.replace("\ufeff", "").strip():
        raise KnowledgeFileExtractionError("Tệp không có nội dung văn bản để xử lý.")
    return text


def extraction_method_for_format(
    file_format: str, *, data: bytes | str | None = None, content_type: str = ""
) -> str:
    """Name the actual parser or decoder; omitted bytes retain the UTF-8 default."""
    parsed = _PARSED_FORMAT_METHODS.get(file_format)
    if parsed is not None:
        return parsed
    encoding = _text_encoding(data, content_type) if isinstance(data, bytes) else "utf-8"
    # UTF-8 with a BOM is still UTF-8 decoding, with its signature removed.
    method = (
        "utf8"
        if encoding in {"utf-8", "utf-8-sig"}
        else encoding.replace("utf-", "utf").replace("-", "_")
    )
    return f"{method}_decode"


def is_parsed_format(file_format: str) -> bool:
    """Whether the format is structurally parsed rather than decoded as text."""
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
    plain text and markdown are decoded losslessly using their Unicode BOM or
    declared charset, with UTF-8 as the default. Invalid bytes, binary content
    and empty text raise ``KnowledgeFileExtractionError`` for a clear 422.

    ``allowed_formats`` narrows resolution to the strict KB-release contract (see
    :func:`_detect_upload_format`). ``decode_errors`` remains for caller
    compatibility, but only ``strict`` is allowed: replacement would silently
    alter source facts before category extraction.
    """
    fmt = _detect_upload_format(file_name, content_type, allowed_formats=allowed_formats)
    parsed = _PARSED_FORMAT_EXTRACTORS.get(fmt)
    if parsed is not None:
        if isinstance(data, str):
            raise KnowledgeFileExtractionError("Tệp Office phải được tải lên dưới dạng tệp gốc.")
        return parsed(data)
    if decode_errors != "strict":
        raise KnowledgeFileExtractionError(
            "Nội dung văn bản phải được giải mã mà không thay thế ký tự."
        )
    if isinstance(data, str):
        return _validate_text(data.lstrip("\ufeff"))
    if data.startswith(_BINARY_SIGNATURES):
        raise KnowledgeFileExtractionError("Tệp nhị phân không phải là tệp văn bản được hỗ trợ.")
    try:
        text = data.decode(_text_encoding(data, content_type), errors="strict")
    except UnicodeError as exc:
        raise KnowledgeFileExtractionError(
            "Không đọc được mã hóa văn bản. Hãy lưu tệp dưới dạng UTF-8 hoặc Unicode có BOM."
        ) from exc
    return _validate_text(text)
