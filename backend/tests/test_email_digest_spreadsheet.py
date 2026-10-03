"""The digest Excel attachment: round-trip the generated workbook bytes.

The writer is stdlib-built, so the tests parse it back with the same stdlib
(zipfile + ElementTree) — valid package, bold header row, inline-string cells,
numeric STT/age, empty cells for details the bot never learned.
"""

import io
import xml.etree.ElementTree as ET
import zipfile

from app.services.email_digest.repository import DigestCandidate
from app.services.email_digest.spreadsheet import (
    XLSX_CONTENT_TYPE,
    build_lead_workbook,
)

_NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}

_EXPECTED_PARTS = {
    "[Content_Types].xml",
    "_rels/.rels",
    "xl/workbook.xml",
    "xl/_rels/workbook.xml.rels",
    "xl/styles.xml",
    "xl/worksheets/sheet1.xml",
}


def _full_candidate() -> DigestCandidate:
    return DigestCandidate(
        lead_id=1,
        name="Nguyễn Văn A & <Công ty>",
        phone="0901 234 567",
        age=27,
        gender="Nam",
        living_area="Hải Phòng",
        address="12 Lê Lợi",
        desired_job="Công nhân sản xuất",
        years_experience="2 năm",
        expected_salary="8-10 triệu",
        channel_label="Zalo Chatbot",
        project_name="LG Display",
        candidate_messages=("Tôi muốn hỏi về việc làm",),
        summary="Ứng viên quan tâm LG Display.",
    )


def _read_rows(content: bytes) -> list[dict[str, tuple[str, str, str | None]]]:
    """Parse sheet1 into per-row ``{ref: (kind, text, style)}`` maps."""
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        assert set(archive.namelist()) == _EXPECTED_PARTS
        for name in archive.namelist():
            ET.fromstring(archive.read(name))  # every part is well-formed XML
        root = ET.fromstring(archive.read("xl/worksheets/sheet1.xml"))
    rows: list[dict[str, tuple[str, str, str | None]]] = []
    for row in root.findall(".//m:sheetData/m:row", _NS):
        cells: dict[str, tuple[str, str, str | None]] = {}
        for cell in row.findall("m:c", _NS):
            ref = cell.get("r", "")
            inline = cell.find("m:is/m:t", _NS)
            number = cell.find("m:v", _NS)
            if inline is not None:
                cells[ref] = ("s", inline.text or "", cell.get("s"))
            elif number is not None:
                cells[ref] = ("n", number.text or "", cell.get("s"))
            else:
                cells[ref] = ("empty", "", cell.get("s"))
        rows.append(cells)
    return rows


def test_workbook_headers_are_bold_and_in_order():
    attachment = build_lead_workbook([_full_candidate()], ict_date="03-10-2026")
    assert attachment.filename == "danh_sach_ung_vien_03-10-2026.xlsx"
    assert attachment.content_type == XLSX_CONTENT_TYPE
    rows = _read_rows(attachment.content)
    assert len(rows) == 2  # header + one candidate
    header = rows[0]
    expected = [
        "STT", "Họ và tên", "Số điện thoại", "Tuổi", "Giới tính", "Khu vực",
        "Địa chỉ", "Việc làm mong muốn", "Kinh nghiệm", "Mức lương mong muốn",
        "Dự án quan tâm", "Nguồn", "Tóm tắt hội thoại",
    ]
    for index, text in enumerate(expected):
        ref = f"{chr(65 + index)}1"
        assert header[ref][0] == "s"
        assert header[ref][1] == text
        assert header[ref][2] == "1", "header cells use the bold style"


def test_candidate_row_carries_all_learned_details():
    rows = _read_rows(build_lead_workbook([_full_candidate()], ict_date="03-10-2026").content)
    row = rows[1]
    assert row["A2"] == ("n", "1", None)
    assert row["B2"] == ("s", "Nguyễn Văn A & <Công ty>", None)  # escaped
    assert row["C2"] == ("s", "0901 234 567", None)
    assert row["D2"] == ("n", "27", None)
    assert row["E2"] == ("s", "Nam", None)
    assert row["K2"] == ("s", "LG Display", None)
    assert row["L2"] == ("s", "Zalo Chatbot", None)
    assert row["M2"] == ("s", "Ứng viên quan tâm LG Display.", None)


def test_missing_details_are_empty_cells_not_placeholders():
    sparse = DigestCandidate(lead_id=2, name="Trần Thị B", phone="0987 654 321")
    rows = _read_rows(build_lead_workbook([sparse], ict_date="03-10-2026").content)
    row = rows[1]
    assert row["B2"] == ("s", "Trần Thị B", None)
    assert row["C2"] == ("s", "0987 654 321", None)
    for ref in ("D2", "E2", "F2", "G2", "H2", "I2", "J2", "K2", "M2"):
        assert row[ref][0] == "empty", ref


def test_sequence_numbers_follow_row_order():
    rows = _read_rows(
        build_lead_workbook(
            [_full_candidate(), DigestCandidate(lead_id=3)], ict_date="03-10-2026"
        ).content
    )
    assert len(rows) == 3
    assert rows[1]["A2"] == ("n", "1", None)
    assert rows[2]["A3"] == ("n", "2", None)


def test_sample_workbook_marks_the_filename():
    attachment = build_lead_workbook(
        [_full_candidate()], ict_date="03-10-2026", test=True
    )
    assert attachment.filename == "danh_sach_ung_vien_mau_03-10-2026.xlsx"
    assert attachment.content_type == XLSX_CONTENT_TYPE
