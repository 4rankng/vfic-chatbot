"""Excel workbook for the candidate digest — the lead list as an attachment.

Built with the standard library (zipfile + minimal OOXML) on purpose: the repo
already hand-parses xlsx with stdlib in ``knowledge/file_extraction.py`` and
carries no spreadsheet dependency, so the writer adds none either. The output
is a single-sheet workbook with inline strings — Excel, Google Sheets and
LibreOffice read it without a sharedStrings part.
"""

from __future__ import annotations

import io
import zipfile
from collections.abc import Sequence
from xml.sax.saxutils import escape

from app.services.email_digest.repository import DigestCandidate
from app.services.email_service import EmailAttachment

# Payroll mirrors this MIME type on its own statement attachments.
XLSX_CONTENT_TYPE = (
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
)

_SHEET_NAME = "Ứng viên"

# (header, candidate attribute, column width) in the sheet's reading order:
# identity first, then the bot-gathered details, then source and summary.
# The single ``None`` attribute is the STT sequence column.
_COLUMNS: tuple[tuple[str, str | None, float], ...] = (
    ("STT", None, 5),
    ("Họ và tên", "name", 24),
    ("Số điện thoại", "phone", 16),
    ("Tuổi", "age", 7),
    ("Giới tính", "gender", 10),
    ("Khu vực", "living_area", 16),
    ("Địa chỉ", "address", 24),
    ("Việc làm mong muốn", "desired_job", 22),
    ("Kinh nghiệm", "years_experience", 14),
    ("Mức lương mong muốn", "expected_salary", 18),
    ("Dự án quan tâm", "project_name", 22),
    ("Nguồn", "channel_label", 16),
    ("Tóm tắt hội thoại", "summary", 60),
)


def _column_xml() -> str:
    cols = "".join(
        f'<col min="{index}" max="{index}" width="{width:g}" customWidth="1"/>'
        for index, (_header, _attr, width) in enumerate(_COLUMNS, start=1)
    )
    return f"<cols>{cols}</cols>"


def _text_cell(ref: str, value: str, *, bold: bool = False) -> str:
    style = ' s="1"' if bold else ""
    return (
        f'<c r="{ref}" t="inlineStr"{style}><is><t xml:space="preserve">'
        f"{escape(value)}</t></is></c>"
    )


def _number_cell(ref: str, value: int, *, bold: bool = False) -> str:
    style = ' s="1"' if bold else ""
    return f'<c r="{ref}"{style}><v>{int(value)}</v></c>'


def _empty_cell(ref: str) -> str:
    return f'<c r="{ref}"/>'


def _row_xml(row_number: int, candidate: DigestCandidate | None) -> str:
    """The bold header row (``candidate=None``) or one candidate row."""
    cells: list[str] = []
    for index, (header, attr, _width) in enumerate(_COLUMNS, start=1):
        ref = f"{chr(64 + index)}{row_number}"
        if candidate is None:
            cells.append(_text_cell(ref, header, bold=True))
        elif attr is None:  # the STT sequence column
            cells.append(_number_cell(ref, row_number - 1))
        else:
            value = getattr(candidate, attr, None)
            if value is None or (isinstance(value, str) and not value.strip()):
                cells.append(_empty_cell(ref))
            elif attr == "age":
                cells.append(_number_cell(ref, int(value)))
            else:
                cells.append(_text_cell(ref, str(value).strip()))
    return f'<row r="{row_number}">{"".join(cells)}</row>'


def _workbook_xml(sheet_name: str) -> str:
    name = escape(sheet_name, {'"': "&quot;"})
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        f'<sheets><sheet name="{name}" sheetId="1" r:id="rId1"/></sheets>'
        "</workbook>"
    )


_STYLES_XML = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
    '<fonts count="2">'
    '<font><sz val="11"/><name val="Calibri"/><family val="2"/></font>'
    '<font><b/><sz val="11"/><name val="Calibri"/><family val="2"/></font>'
    "</fonts>"
    '<fills count="2">'
    '<fill><patternFill patternType="none"/></fill>'
    '<fill><patternFill patternType="gray125"/></fill>'
    "</fills>"
    '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>'
    '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
    '<cellXfs count="2">'
    '<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
    '<xf numFmtId="0" fontId="1" fillId="0" borderId="0" xfId="0" applyFont="1"/>'
    "</cellXfs>"
    '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>'
    "</styleSheet>"
)


def build_lead_workbook(
    candidates: Sequence[DigestCandidate],
    *,
    ict_date: str,
    test: bool = False,
) -> EmailAttachment:
    """The lead list as a single-sheet xlsx email attachment.

    ``ict_date`` ("DD-MM-YYYY") stamps the filename; ``test=True`` marks the
    filename so a sample workbook is never mistaken for a real digest. Rows
    carry the bot-gathered details — a detail the bot never learned is an
    empty cell, never a placeholder.
    """
    rows = "".join(
        _row_xml(number, candidate)
        for number, candidate in enumerate([None, *candidates], start=1)
    )
    sheet = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f"{_column_xml()}<sheetData>{rows}</sheetData>"
        "</worksheet>"
    )
    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
        "</Types>"
    )
    root_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
        'Target="xl/workbook.xml"/>'
        "</Relationships>"
    )
    workbook_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
        'Target="worksheets/sheet1.xml"/>'
        '<Relationship Id="rId2" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" '
        'Target="styles.xml"/>'
        "</Relationships>"
    )
    parts: dict[str, str] = {
        "[Content_Types].xml": content_types,
        "_rels/.rels": root_rels,
        "xl/workbook.xml": _workbook_xml(_SHEET_NAME),
        "xl/_rels/workbook.xml.rels": workbook_rels,
        "xl/styles.xml": _STYLES_XML,
        "xl/worksheets/sheet1.xml": sheet,
    }
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for part_name, xml_text in parts.items():
            archive.writestr(part_name, xml_text)
    filename = (
        f"danh_sach_ung_vien_mau_{ict_date}.xlsx"
        if test
        else f"danh_sach_ung_vien_{ict_date}.xlsx"
    )
    return EmailAttachment(
        filename=filename,
        content_type=XLSX_CONTENT_TYPE,
        content=buffer.getvalue(),
    )
