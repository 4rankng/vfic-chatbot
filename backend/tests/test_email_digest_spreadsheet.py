"""Round-trip tests for the digest workbook: generate, read the bytes back.

Content assertions run through the repo's own production xlsx reader
(``knowledge/file_extraction.py``, stdlib) so the writer is validated by an
independent parser; styling facts the text extractor cannot see (styles,
freeze pane, auto-filter, merges) are asserted on the raw sheet XML.
"""

# pyright: reportArgumentType=false

import io
import re
import zipfile

from app.services.email_digest.repository import DigestCandidate
from app.services.email_digest.spreadsheet import (
    XLSX_CONTENT_TYPE,
    build_lead_workbook,
)
from app.services.knowledge.file_extraction import _extract_xlsx_text


def _full_candidate(**overrides) -> DigestCandidate:
    values: dict = {
        "lead_id": 1,
        "name": "Nguyễn Văn A & <Công ty>",
        "phone": "0365717912",
        "age": 27,
        "living_area": "Hải Phòng",
        "project_name": "LG Display",
        "channel_label": "Messenger",
        "summary": "Hỏi về ca làm và lương.",
    }
    values.update(overrides)
    return DigestCandidate(**values)


def _parts(content: bytes) -> dict[str, str]:
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        return {name: archive.read(name).decode() for name in archive.namelist()}


def _sheet(content: bytes) -> str:
    return _parts(content)["xl/worksheets/sheet1.xml"]


def _cell_style(sheet: str, ref: str) -> str:
    match = re.search(rf'<c r="{ref}"[^>]*s="(\d+)"', sheet)
    assert match is not None, f"cell {ref} not found in sheet"
    return match.group(1)


def test_attachment_metadata():
    workbook = build_lead_workbook([_full_candidate()], ict_date="03-10-2026")
    assert workbook.filename == "danh_sach_ung_vien_03-10-2026.xlsx"
    assert workbook.content_type == XLSX_CONTENT_TYPE
    assert workbook.content[:2] == b"PK"  # a real zip archive
    sample = build_lead_workbook(
        [_full_candidate()], ict_date="03-10-2026", test=True
    )
    assert sample.filename == "danh_sach_ung_vien_mau_03-10-2026.xlsx"


def test_title_banner_header_and_layout():
    sheet = _sheet(build_lead_workbook([_full_candidate()], ict_date="03-10-2026").content)
    # One merged, dated title banner over a styled header row.
    assert "Danh sách ứng viên mới — 03/10/2026" in sheet
    assert '<mergeCell ref="A1:H1"/>' in sheet
    assert '<row r="1" ht="30"' in sheet
    headers = [
        "STT",
        "Họ và tên",
        "Số điện thoại",
        "Tuổi",
        "Khu vực",
        "Dự án quan tâm",
        "Nguồn",
        "Tóm tắt hội thoại",
    ]
    for index, header in enumerate(headers, start=1):
        assert (
            f'<c r="{chr(64 + index)}2" t="inlineStr" s="2">'
            f'<is><t xml:space="preserve">{header}</t></is></c>' in sheet
        )
    assert '<row r="2" ht="22"' in sheet
    # Frozen header, auto-filter spanning the table, ordered worksheet parts.
    assert 'pane ySplit="2" topLeftCell="A3"' in sheet and 'state="frozen"' in sheet
    assert '<autoFilter ref="A2:H3"/>' in sheet  # 1 candidate → data ends at row 3
    order = [sheet.index(part) for part in
             ("<sheetViews>", "<cols>", "<sheetData>", "<autoFilter", "<mergeCells")]
    assert order == sorted(order)


def test_full_row_content():
    text = _extract_xlsx_text(
        build_lead_workbook([_full_candidate()], ict_date="03-10-2026").content
    )
    lines = [line for line in text.splitlines() if line.strip()]
    assert len(lines) == 3  # title, header, one data row
    assert lines[2] == (
        "1\tNguyễn Văn A & <Công ty>\t0365717912\t27\tHải Phòng"
        "\tLG Display\tMessenger\tHỏi về ca làm và lương."
    )


def test_missing_fields_blank_and_summary_fallback():
    candidate = _full_candidate(
        name=None,
        age=None,
        living_area="Vũ Thư",
        project_name=None,
        summary=None,
        candidate_messages=("Hỏi lương", "Hỏi vị trí", "Hỏi ca làm"),
    )
    text = _extract_xlsx_text(
        build_lead_workbook([candidate], ict_date="03-10-2026").content
    )
    lines = [line for line in text.splitlines() if line.strip()]
    assert lines[2] == "1\t\t0365717912\t\tVũ Thư\t\tMessenger\tHỏi lương · Hỏi vị trí · Hỏi ca làm"

    silent = _full_candidate(summary=None, candidate_messages=())
    text = _extract_xlsx_text(
        build_lead_workbook([silent], ict_date="03-10-2026").content
    )
    lines = [line for line in text.splitlines() if line.strip()]
    assert lines[2].endswith("\t")


def test_phone_stays_text_with_leading_zero():
    sheet = _sheet(build_lead_workbook([_full_candidate()], ict_date="03-10-2026").content)
    assert '<c r="C3" t="inlineStr"' in sheet  # never a number cell: 03… must survive


def test_sequence_numbers_across_rows():
    candidates = [_full_candidate(lead_id=lead_id) for lead_id in (1, 2, 3)]
    text = _extract_xlsx_text(
        build_lead_workbook(candidates, ict_date="03-10-2026").content
    )
    lines = [line for line in text.splitlines() if line.strip()]
    assert [line.split("\t")[0] for line in lines[2:]] == ["1", "2", "3"]


def test_data_cell_styles_and_banding():
    candidates = [_full_candidate(lead_id=1), _full_candidate(lead_id=2)]
    sheet = _sheet(build_lead_workbook(candidates, ict_date="03-10-2026").content)
    # Row 3 plain, row 4 banded — the same shift per column kind.
    assert _cell_style(sheet, "B3") == "3"
    assert _cell_style(sheet, "B4") == "4"
    assert _cell_style(sheet, "H3") == "5"  # wrapped summary
    assert _cell_style(sheet, "H4") == "6"
    assert _cell_style(sheet, "A3") == "7"  # centered STT
    assert _cell_style(sheet, "A4") == "8"
    assert _cell_style(sheet, "A1") == "1"  # title banner
    assert _cell_style(sheet, "B2") == "2"  # header row
