"""Excel workbook for the candidate digest — the lead list as an attachment.

Built with the standard library (zipfile + minimal OOXML) on purpose: the repo
already hand-parses xlsx with stdlib in ``knowledge/file_extraction.py`` and
carries no spreadsheet dependency, so the writer adds none either. The output
is a single-sheet business report — merged title banner, styled frozen header,
banded rows, auto-filter — that Excel, Google Sheets and LibreOffice all read
(inline strings, no sharedStrings part).
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

# (header, candidate attribute, column width, cell kind). ``kind`` picks the
# data-cell style: "center" for sequence/number columns, "wrap" for the long
# summary text, "text" for the rest. The single ``None`` attribute is the STT
# sequence column. "Dự án quan tâm" is wide because an ambiguous channel
# mapping prints every project it could mean, not just one. "Quảng cáo" names
# the ad/campaign a candidate entered from — blank when the entry had none.
_COLUMNS: tuple[tuple[str, str | None, float, str], ...] = (
    ("STT", None, 6, "center"),
    ("Họ và tên", "name", 26, "text"),
    ("Số điện thoại", "phone", 18, "text"),
    ("Tuổi", "age", 7, "center"),
    ("Khu vực", "living_area", 18, "text"),
    ("Dự án quan tâm", "project_name", 30, "text"),
    ("Nguồn", "channel_label", 14, "text"),
    ("Quảng cáo", "campaign", 26, "text"),
    ("Tóm tắt hội thoại", "summary", 70, "wrap"),
)

# Style indexes into styles.xml cellXfs (see _STYLES_XML): 1 = title banner,
# 2 = header row, 3-8 = data cells per kind (plain, banded).
_TITLE_STYLE = "1"
_HEADER_STYLE = "2"
_DATA_STYLES: dict[str, tuple[str, str]] = {  # kind -> (plain, banded)
    "text": ("3", "4"),
    "wrap": ("5", "6"),
    "center": ("7", "8"),
}


def _column_xml() -> str:
    cols = "".join(
        f'<col min="{index}" max="{index}" width="{width:g}" customWidth="1"/>'
        for index, (_header, _attr, width, _kind) in enumerate(_COLUMNS, start=1)
    )
    return f"<cols>{cols}</cols>"


def _candidate_value(candidate: DigestCandidate, attr: str) -> str | int | None:
    """The cell value for one attribute.

    ``summary`` is written only when the LLM actually produced one. There is
    deliberately no fallback to the candidate's verbatim messages: that fallback
    shipped a recruiter sheet whose "Tóm tắt hội thoại" column was the last
    three messages joined by " · " — a cut-and-paste of the transcript wearing a
    summary's header, which is worse than an empty cell because it looks
    summarised. A blank summary now means "the summarizer could not answer",
    which is honest and fixable; a pasted transcript is neither.
    """
    value = getattr(candidate, attr, None)
    if attr == "summary":
        text = str(value or "").strip()
        return text or None
    return value


def _text_cell(ref: str, value: str, style: str) -> str:
    return (
        f'<c r="{ref}" t="inlineStr" s="{style}"><is><t xml:space="preserve">'
        f"{escape(value)}</t></is></c>"
    )


def _number_cell(ref: str, value: int, style: str) -> str:
    return f'<c r="{ref}" s="{style}"><v>{int(value)}</v></c>'


def _styled_blank(ref: str, style: str) -> str:
    """A valueless cell that still paints its style (banding, borders)."""
    return f'<c r="{ref}" s="{style}"/>'


def _title_row(ict_date: str, column_count: int) -> str:
    blanks = "".join(
        _styled_blank(f"{chr(64 + index)}1", _TITLE_STYLE)
        for index in range(2, column_count + 1)
    )
    title = f"Danh sách ứng viên mới — {ict_date.replace('-', '/')}"
    return (
        '<row r="1" ht="30" customHeight="1">'
        f'{_text_cell("A1", title, _TITLE_STYLE)}{blanks}</row>'
    )


def _header_row() -> str:
    cells = "".join(
        _text_cell(f"{chr(64 + index)}2", header, _HEADER_STYLE)
        for index, (header, _attr, _width, _kind) in enumerate(_COLUMNS, start=1)
    )
    return f'<row r="2" ht="22" customHeight="1">{cells}</row>'


def _data_row(row_number: int, candidate: DigestCandidate) -> str:
    """One candidate row; banding alternates from the first data row (3)."""
    banded = (row_number - 3) % 2 == 1
    cells: list[str] = []
    for index, (_header, attr, _width, kind) in enumerate(_COLUMNS, start=1):
        ref = f"{chr(64 + index)}{row_number}"
        style = _DATA_STYLES[kind][1 if banded else 0]
        if attr is None:  # the STT sequence column
            cells.append(_number_cell(ref, row_number - 2, style))
            continue
        value = _candidate_value(candidate, attr)
        if value is None or (isinstance(value, str) and not value.strip()):
            cells.append(_styled_blank(ref, style))
        elif attr == "age":
            cells.append(_number_cell(ref, int(value), style))
        else:
            cells.append(_text_cell(ref, str(value).strip(), style))
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
    '<fonts count="3">'
    '<font><sz val="11"/><name val="Calibri"/><family val="2"/></font>'
    '<font><b/><sz val="11"/><color rgb="FFFFFFFF"/><name val="Calibri"/><family val="2"/></font>'
    '<font><b/><sz val="14"/><color rgb="FFFFFFFF"/><name val="Calibri"/><family val="2"/></font>'
    "</fonts>"
    '<fills count="5">'
    '<fill><patternFill patternType="none"/></fill>'
    '<fill><patternFill patternType="gray125"/></fill>'
    '<fill><patternFill patternType="solid"><fgColor rgb="FF0F172A"/><bgColor indexed="64"/></patternFill></fill>'
    '<fill><patternFill patternType="solid"><fgColor rgb="FF2563EB"/><bgColor indexed="64"/></patternFill></fill>'
    '<fill><patternFill patternType="solid"><fgColor rgb="FFF8FAFC"/><bgColor indexed="64"/></patternFill></fill>'
    "</fills>"
    '<borders count="2">'
    "<border><left/><right/><top/><bottom/><diagonal/></border>"
    '<border><left style="thin"><color rgb="FFDCE3ED"/></left>'
    '<right style="thin"><color rgb="FFDCE3ED"/></right>'
    '<top style="thin"><color rgb="FFDCE3ED"/></top>'
    '<bottom style="thin"><color rgb="FFDCE3ED"/></bottom><diagonal/></border>'
    "</borders>"
    '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
    '<cellXfs count="9">'
    '<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
    '<xf numFmtId="0" fontId="2" fillId="2" borderId="0" xfId="0" applyFont="1" applyFill="1" applyAlignment="1"><alignment horizontal="center" vertical="center"/></xf>'
    '<xf numFmtId="0" fontId="1" fillId="3" borderId="1" xfId="0" applyFont="1" applyFill="1" applyBorder="1" applyAlignment="1"><alignment horizontal="center" vertical="center"/></xf>'
    '<xf numFmtId="0" fontId="0" fillId="0" borderId="1" xfId="0" applyBorder="1" applyAlignment="1"><alignment vertical="top"/></xf>'
    '<xf numFmtId="0" fontId="0" fillId="4" borderId="1" xfId="0" applyFill="1" applyBorder="1" applyAlignment="1"><alignment vertical="top"/></xf>'
    '<xf numFmtId="0" fontId="0" fillId="0" borderId="1" xfId="0" applyBorder="1" applyAlignment="1"><alignment vertical="top" wrapText="1"/></xf>'
    '<xf numFmtId="0" fontId="0" fillId="4" borderId="1" xfId="0" applyFill="1" applyBorder="1" applyAlignment="1"><alignment vertical="top" wrapText="1"/></xf>'
    '<xf numFmtId="0" fontId="0" fillId="0" borderId="1" xfId="0" applyBorder="1" applyAlignment="1"><alignment horizontal="center" vertical="top"/></xf>'
    '<xf numFmtId="0" fontId="0" fillId="4" borderId="1" xfId="0" applyFill="1" applyBorder="1" applyAlignment="1"><alignment horizontal="center" vertical="top"/></xf>'
    "</cellXfs>"
    '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>'
    "</styleSheet>"
)


def build_lead_workbook(
    candidates: Sequence[DigestCandidate],
    *,
    ict_date: str,
) -> EmailAttachment:
    """The lead list as a single-sheet xlsx email attachment.

    ``ict_date`` ("DD-MM-YYYY") stamps the filename and the title banner.
    Rows carry the bot-gathered details — a detail the bot never learned is
    an empty cell, never a placeholder. Layout: row 1 title banner (merged),
    row 2 header (frozen + auto-filter), data from row 3.
    """
    column_count = len(_COLUMNS)
    last_col = chr(64 + column_count)
    last_row = 2 + len(candidates)
    rows = "".join(
        [
            _title_row(ict_date, column_count),
            _header_row(),
            *(
                _data_row(number, candidate)
                for number, candidate in enumerate(candidates, start=3)
            ),
        ]
    )
    sheet = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        '<sheetViews><sheetView workbookViewId="0">'
        '<pane ySplit="2" topLeftCell="A3" activePane="bottomLeft" state="frozen"/>'
        "</sheetView></sheetViews>"
        f"{_column_xml()}<sheetData>{rows}</sheetData>"
        f'<autoFilter ref="A2:{last_col}{last_row}"/>'
        f'<mergeCells count="1"><mergeCell ref="A1:{last_col}1"/></mergeCells>'
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
    filename = f"danh_sach_ung_vien_{ict_date}.xlsx"
    return EmailAttachment(
        filename=filename,
        content_type=XLSX_CONTENT_TYPE,
        content=buffer.getvalue(),
    )
