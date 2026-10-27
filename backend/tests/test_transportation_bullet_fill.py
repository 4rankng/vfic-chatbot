"""CHAT-13 pin: the importer must map multi-line bullet lists into stops/notes.

The extraction LLM dropped the golden brief's nested ordered list ("Tuyến & điểm
đón cố định:" → 1..4) and the other-areas condition bullet ("Các khu vực khác:
… gom đủ từ 5 người trở lên") from the transportation record. The deterministic
completion re-reads the brief section and fills only the empty fields; grounding
still runs afterwards.
"""

from __future__ import annotations

import pytest

from app.services.knowledge.category_plan_grounding import validate_category_envelope
from app.services.knowledge.transportation_bullet_fill import (
    brief_category_section,
    complete_transportation_record,
)

GOLDEN_SECTION = """## Đưa đón & lịch xe
- **Xe đưa đón:** CÓ xe đưa đón công nhân viên (áp dụng cả khi đi phỏng vấn).
- **Tuyến & điểm đón cố định:**
  1. Tuyến Đồ Sơn.
  2. Tuyến Thư viện thành phố Hải Phòng.
  3. Tuyến Nhà thi đấu Kiến Thụy.
  4. Tuyến Bến xe Thượng Lý.
- **Các khu vực khác:** Các địa điểm như An Lão, An Dương, Tiên Lãng công ty sẽ điều phối xe đưa đón khi gom đủ từ 5 người trở lên.
- **Chi phí xe đưa đón:** Miễn phí theo chính sách công ty.
"""

DEEPSEEK_SECTION = """## Đưa đón & lịch xe
- **Xe đưa đón:** CÓ xe đưa đón.
- **Tuyến & điểm đón:**
  1. Đồ Sơn
  2. Thư viện thành phố
  3. Nhà thi đấu Kiến Thụy
  4. Bến xe Thượng Lý
  5. Các địa điểm khác như An Lão, An Dương, Tiên Lãng phải gom đủ 5 người trở lên mới điều xe đón.
- **Chi phí:** Miễn phí (xe công ty).
- **Tự túc đi lại:** Được hưởng phụ cấp xăng xe, đi lại trong khoản phụ cấp 1,3 triệu/tháng.
"""


def _full_source(section: str) -> str:
    return (
        "# Dự án Công ty TNHH Lear Việt Nam\n\n"
        "## Thông tin tổng quan\n"
        "- **Tên dự án:** Công ty TNHH Lear Việt Nam\n\n" + section + "\n## Bảo hiểm\n"
        "- **Chế độ BHXH/BHYT/BHTN:** Được tham gia đầy đủ.\n"
    )


def test_section_finder_resolves_the_transportation_heading():
    assert "Tuyến & điểm đón cố định" in brief_category_section(
        _full_source(GOLDEN_SECTION), ("Đưa đón & lịch xe", "Đưa đón")
    )
    # Sections outside the heading are not captured.
    section = brief_category_section(_full_source(GOLDEN_SECTION), ("Đưa đón & lịch xe",))
    assert "BHXH" not in section
    assert brief_category_section(_full_source(GOLDEN_SECTION), ("Không có mục này",)) == ""


def test_completion_fills_stops_and_area_note_from_the_golden_bullets():
    record = {
        "name": "Xe đưa đón",
        "direction": "round_trip",
        "fee_vnd": 0,
        "stops": [],
        "notes": None,
    }
    filled = complete_transportation_record(record, _full_source(GOLDEN_SECTION))
    assert [stop["name"] for stop in filled["stops"]] == [
        "Tuyến Đồ Sơn",
        "Tuyến Thư viện thành phố Hải Phòng",
        "Tuyến Nhà thi đấu Kiến Thụy",
        "Tuyến Bến xe Thượng Lý",
    ]
    assert [stop["order"] for stop in filled["stops"]] == [1, 2, 3, 4]
    assert filled["notes"] == (
        "Các địa điểm như An Lão, An Dương, Tiên Lãng công ty sẽ điều phối xe đưa đón "
        "khi gom đủ từ 5 người trở lên."
    )
    # Single-line facts the model already mapped stay untouched.
    assert filled["name"] == "Xe đưa đón"
    assert filled["fee_vnd"] == 0


def test_completion_fills_the_numbered_condition_as_the_fifth_stop():
    """The deepseek variant lists the ≥5-people rule as item 5 of the route."""
    record = {"name": "Xe đưa đón", "direction": "round_trip", "stops": [], "notes": None}
    filled = complete_transportation_record(record, _full_source(DEEPSEEK_SECTION))
    names = [stop["name"] for stop in filled["stops"]]
    assert names[:4] == ["Đồ Sơn", "Thư viện thành phố", "Nhà thi đấu Kiến Thụy", "Bến xe Thượng Lý"]
    assert names[4] == (
        "Các địa điểm khác như An Lão, An Dương, Tiên Lãng phải gom đủ 5 người trở lên mới điều xe đón"
    )


def test_completion_is_a_noop_when_fields_are_already_grounded():
    record = {
        "name": "Xe đưa đón",
        "direction": "round_trip",
        "stops": [{"order": 1, "name": "Tuyến Đồ Sơn", "time": None, "address": None}],
        "notes": "Đã có ghi chú từ extractor.",
    }
    filled = complete_transportation_record(dict(record), _full_source(GOLDEN_SECTION))
    assert filled == record


def test_completion_appends_list_items_the_extractor_dropped_from_the_tail():
    """CHAT-13 v3: the extractor kept stops 1-4 and dropped item 5 (≥5 người).

    A partial list is completed in list order — the trailing condition item must
    not fall off the end just because the extractor filled SOME stops.
    """
    record = {
        "name": "Xe đưa đón",
        "direction": "round_trip",
        "fee_vnd": 0,
        "stops": [
            {"order": 1, "name": "Đồ Sơn", "time": None, "address": None},
            {"order": 2, "name": "Thư viện thành phố", "time": None, "address": None},
            {"order": 3, "name": "Nhà thi đấu Kiến Thụy", "time": None, "address": None},
            {"order": 4, "name": "Bến xe Thượng Lý", "time": None, "address": None},
        ],
        "notes": None,
    }
    filled = complete_transportation_record(record, _full_source(DEEPSEEK_SECTION))
    names = [stop["name"] for stop in filled["stops"]]
    assert names[:4] == ["Đồ Sơn", "Thư viện thành phố", "Nhà thi đấu Kiến Thụy", "Bến xe Thượng Lý"]
    assert names[4] == (
        "Các địa điểm khác như An Lão, An Dương, Tiên Lãng phải gom đủ 5 người trở lên mới điều xe đón"
    )
    assert [stop["order"] for stop in filled["stops"]] == [1, 2, 3, 4, 5]


def test_completion_does_not_duplicate_stops_the_record_already_has():
    record = {
        "name": "Xe đưa đón",
        "direction": "round_trip",
        "stops": [
            {"order": 1, "name": "Đồ Sơn", "time": None, "address": None},
            {"order": 2, "name": "Thư viện thành phố", "time": None, "address": None},
            {"order": 3, "name": "Nhà thi đấu Kiến Thụy", "time": None, "address": None},
            {"order": 4, "name": "Bến xe Thượng Lý", "time": None, "address": None},
            {
                "order": 5,
                "name": (
                    "Các địa điểm khác như An Lão, An Dương, Tiên Lãng phải gom đủ 5 người "
                    "trở lên mới điều xe đón"
                ),
                "time": None,
                "address": None,
            },
        ],
        "notes": None,
    }
    filled = complete_transportation_record(record, _full_source(DEEPSEEK_SECTION))
    assert len(filled["stops"]) == 5


def test_completion_ignores_sources_without_the_heading():
    record = {"name": "Xe đưa đón", "direction": "round_trip", "stops": [], "notes": None}
    source = "## Lương & thu nhập\n- **Lương cơ bản:** 7.500.000 VNĐ / tháng.\n"
    filled = complete_transportation_record(record, source)
    assert filled["stops"] == []
    assert filled["notes"] is None


def test_grounding_accepts_the_completed_record_end_to_end():
    """The completed envelope passes the real grounding + schema validation."""
    envelope = {
        "record": {
            "name": "Xe đưa đón",
            "direction": "round_trip",
            "fee_vnd": 0,
            "stops": [],
            "notes": None,
        },
        "source_quotes": ["- **Xe đưa đón:** CÓ xe đưa đón công nhân viên (áp dụng cả khi đi phỏng vấn)."],
    }
    source = _full_source(GOLDEN_SECTION)
    validated = validate_category_envelope("transportation", envelope, source)
    record = validated["record"]
    assert [stop["name"] for stop in record["stops"]] == [
        "Tuyến Đồ Sơn",
        "Tuyến Thư viện thành phố Hải Phòng",
        "Tuyến Nhà thi đấu Kiến Thụy",
        "Tuyến Bến xe Thượng Lý",
    ]
    assert record["notes"].startswith("Các địa điểm như An Lão")
    assert record["id"].startswith("auto-transportation-")


def test_grounding_still_rejects_unsupported_completed_values():
    """A completed name that is not verbatim source text is still cleared."""
    envelope = {
        "record": {"name": "Xe đưa đón", "direction": "round_trip", "stops": []},
        "source_quotes": ["- **Xe đưa đón:** CÓ xe đưa đón."],
    }
    source = _full_source(DEEPSEEK_SECTION)
    validated = validate_category_envelope("transportation", envelope, source)
    record = validated["record"]
    names = [stop["name"] for stop in record["stops"]]
    assert "Nhà máy Starlink" not in names  # never invented
    assert "Đồ Sơn" in names


@pytest.mark.parametrize("section", [GOLDEN_SECTION, DEEPSEEK_SECTION])
def test_every_completed_stop_name_is_verbatim_source_text(section):
    record = {"name": "Xe đưa đón", "direction": "round_trip", "stops": [], "notes": None}
    filled = complete_transportation_record(record, _full_source(section))
    source = _full_source(section)
    for stop in filled["stops"]:
        assert stop["name"].replace("Tuyến ", "") in source or stop["name"] in source
