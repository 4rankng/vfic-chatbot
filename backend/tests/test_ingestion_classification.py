"""Tests for section classification (Tech-Lead Directive §9 stage 5)."""

from __future__ import annotations

from app.services.ingestion.classification import (
    classify_fragment,
    classify_fragments,
)


def test_classify_bus_timetable_by_keyword():
    c = classify_fragment("Tuyến xe đưa rước B03 từ Biên Hòa")
    assert c.section_type == "bus_timetable"
    assert c.method == "rule"
    assert c.confidence > 0.6


def test_classify_benefit_by_keyword():
    c = classify_fragment("Phụ cấp chuyên cần 500,000 VND/tháng")
    assert c.section_type == "benefit"
    assert c.method == "rule"


def test_classify_working_hours_by_keyword():
    c = classify_fragment("Ca sáng từ 8 giờ đến 17 giờ")
    assert c.section_type == "working_hours"


def test_classify_job_requirements_by_keyword():
    c = classify_fragment("Yêu cầu: Nam, 18-35 tuổi, tốt nghiệp THPT")
    assert c.section_type == "job_requirements"


def test_classify_unknown_when_no_keyword_matches():
    c = classify_fragment("Đây là đoạn văn bản không chứa từ khóa nào cụ thể.")
    assert c.section_type == "unknown"
    assert c.method == "unknown"
    assert c.confidence == 0.0


def test_classify_heading_inheritance():
    """A fragment under a 'Phúc lợi' heading inherits 'benefit'."""
    c = classify_fragment("500,000 VND", heading_context="benefit")
    assert c.section_type == "benefit"
    assert c.method == "heading_inheritance"
    assert c.confidence == 0.5


def test_classify_fragments_heading_propagation():
    """Once a confident heading is found, subsequent unknowns inherit it."""
    fragments = [
        "Phúc lợi của công ty:",  # benefit (heading)
        "500,000 VND/tháng",  # no keyword → inherits benefit
        "Bảo hiểm y tế đầy đủ",  # benefit (own keyword)
        "B03 → Factory A 06:10",  # bus (new heading)
        "06:40 07:10",  # no keyword → inherits bus
    ]
    results = classify_fragments(fragments)
    assert results[0].section_type == "benefit"
    assert results[1].section_type == "benefit"  # inherited
    assert results[2].section_type == "benefit"
    assert results[3].section_type == "bus_timetable"
    assert results[4].section_type == "bus_timetable"  # inherited


def test_classify_accent_stripped_variant_matches():
    """'xe dua ruoc' (no diacritics) matches the bus rule."""
    c = classify_fragment("xe dua ruoc tuyen B07")
    assert c.section_type == "bus_timetable"


def test_classify_multiple_keyword_hits_ranks_by_count():
    """A fragment with multiple distinct benefit keywords wins over one."""
    single = classify_fragment("Phụ cấp chuyên cần")
    multi = classify_fragment("Phụ cấp chuyên cần, bảo hiểm y tế, trợ cấp nhà ở")
    assert multi.confidence >= single.confidence
    assert multi.section_type == "benefit"
    assert len(multi.matched_keywords) >= 2
