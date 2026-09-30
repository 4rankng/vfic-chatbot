"""Contract tests for Category Markdown v1 (parser, renderer, templates).

The round-trip cases double as the safety net for the data migration: the renderer
emits every pydantic field in schema order with type-faithful scalars, so
``parse(build(payload))`` must equal the input payload by strict dict equality.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.schemas.knowledge_categories import (
    CATEGORY_DOCUMENT_MODELS,
    KnowledgeCategoryKey,
)
from app.services.knowledge import category_contracts
from app.services.knowledge.category_markdown import (
    CategoryMarkdownError,
    _field_kinds,
    _record_model,
    build_source_markdown,
    parse_category_markdown,
)

TEMPLATE_DIR = Path(category_contracts.__file__).parent / "templates" / "categories"

JOBS_RECORD = {
    "id": "vi-cong-nhan",
    "title": "Công nhân sản xuất",
    "aliases": ["Công nhân kiểm tra màn hình", "CN đóng gói"],
    "location": "KCN VSIP, Thủy Nguyên, Hải Phòng",
    "vacancies": 100,
    "employment_type": "temporary",
    "summary": 'Dây chuyền điện tử, dấu nháy "và" xuống dòng\nthứ hai',
    "keywords": ["điện tử", "kiểm tra"],
}
FULL_RECORDS: dict[str, dict] = {
    "jobs": JOBS_RECORD,
    "compensation": {
        "id": "thu-nhap-chung",
        "job_ids": ["vi-cong-nhan"],
        "base_salary_vnd": 6300000,
        "estimated_income_min_vnd": 9000000,
        "estimated_income_max_vnd": 12000000,
        "allowances": [
            {"name": "Hỗ trợ đời sống", "amount_vnd": 700000, "cadence": "month", "conditions": None},
            {"name": "Trợ cấp ca đêm", "amount_vnd": 50000, "cadence": "shift", "conditions": "Mỗi đêm thực tế"},
        ],
        "bonuses": [
            {"name": "Thưởng năng suất", "amount_vnd": 1000000, "cadence": "month", "conditions": None},
        ],
        "overtime_notes": None,
        "payment_notes": "Chuyển khoản hàng tháng",
    },
    "requirements": {
        "id": "yeu-cau-chung",
        "job_ids": ["vi-cong-nhan"],
        "age_min": 18,
        "age_max": 37,
        "genders": ["any"],
        "education": "Không yêu cầu bằng cấp",
        "experience": "Được đào tạo từ đầu",
        "health": ["Khám sức khỏe đạt"],
        "skills": ["Cẩn thận"],
        "required_documents": ["CCCD bản gốc"],
        "other": ["Nhận người có hình xăm"],
    },
    "work_schedules": {
        "id": "lich-lam-chung",
        "job_ids": ["vi-cong-nhan"],
        "work_days": ["Thứ 2", "Thứ 7"],
        "shifts": [
            {"name": "Ca ngày", "start_time": "07:30", "end_time": "16:30", "crosses_midnight": False},
            {"name": "Ca đêm", "start_time": "20:00", "end_time": "05:00", "crosses_midnight": True},
        ],
        "rotation": "Luân phiên theo tuần",
        "breaks": ["Nghỉ trưa 12:00 - 13:00"],
        "overtime": "Tối thiểu 1 giờ mới tính",
        "notes": None,
    },
    "benefits": {
        "id": "chuyen-can",
        "job_ids": [],
        "name": "Phụ cấp chuyên cần",
        "description": "Cộng vào lương tháng",
        "eligibility": "Đủ công trong tháng",
    },
    "accommodation": {
        "id": "ky-tuc-xa",
        "job_ids": [],
        "available": True,
        "type": "Ký túc xá",
        "address": "Trong khuôn viên KCN",
        "monthly_cost_vnd": 300000,
        "deposit_vnd": 300000,
        "included_services": ["Điện", "Nước"],
        "eligibility": "Người ở xa",
        "notes": None,
    },
    "meals": {
        "id": "bua-an-ca",
        "job_ids": [],
        "provided": True,
        "meals_per_shift": 1,
        "allowance_vnd": 0,
        "menu_notes": "Cơm ba món",
        "eligibility": "Mọi công nhân",
        "notes": None,
    },
    "transportation": {
        "id": "tuyen-xe-1",
        "job_ids": [],
        "name": "Tuyến số 1",
        "direction": "round_trip",
        "service_days": ["Thứ 2"],
        "shift": "Ca ngày",
        "fee_vnd": 0,
        "stops": [
            {"order": 1, "name": "Cửa KCN", "time": "06:45", "address": None},
            {"order": 2, "name": "Bến xe", "time": "07:00", "address": "Số 1 Đường A"},
        ],
        "notes": None,
    },
    "insurance": {
        "id": "bhxh",
        "job_ids": [],
        "name": "BHXH bắt buộc",
        "provider": "Bảo hiểm xã hội",
        "employee_contribution": "10,5%",
        "employer_contribution": "17,5%",
        "coverage": ["Ốm đau", "Hưu trí"],
        "starts_after": "Ngày chính thức",
        "eligibility": "Người làm việc chính thức",
        "notes": None,
    },
    "application": {
        "id": "ung-tuyen-nhan-viec",
        "job_ids": [],
        "application_steps": ["Đăng ký", "Phỏng vấn", "Khám sức khỏe"],
        "required_documents": ["CCCD photo công chứng"],
        "interview_location": "Văn phòng tại KCN",
        "interview_process": "Phỏng vấn trực tiếp",
        "onboarding_steps": ["Nhận việc", "Đào tạo"],
        "processing_time": "1-3 ngày",
        "fees": "Miễn phí",
        "notes": None,
    },
    "contacts": {
        "id": "lien-he-chung",
        "name": "Ngọc Thảo",
        "role": "Phụ trách hồ sơ",
        "phone": "0963019380",
        "zalo": "0963019380",
        "email": "tuyendung@example.com",
        "address": "Văn phòng tại KCN",
        "working_hours": "08:00 - 17:00",
        "notes": None,
    },
    "faq": {
        "id": "cau-hoi-1",
        "question": "Công ty có tuyển vị trí nào không?",
        "answer": "Đang tuyển Công nhân sản xuất.",
        "tags": ["tuyen-dung"],
        "question_variants": ["Bên mình tuyển gì?", "Có việc nào không?"],
        "required_terms": ["tuyển"],
        "forbidden_terms": [],
    },
}


def _payload(key: str) -> dict:
    return {"schema_version": "1.0", "category": key, key: [FULL_RECORDS[key]]}


_JOBS_DOC_PREFIX = (
    "---\n"
    'schema_version: "1.0"\n'
    "category: jobs\n"
    "---\n"
    "\n"
    "## jobs\n"
    "\n"
)


def test_round_trip_full_record_for_every_category():
    for key in KnowledgeCategoryKey:
        payload = _payload(key.value)
        markdown = build_source_markdown(payload)
        document = parse_category_markdown(key, markdown, allow_empty=True)
        assert document.model_dump(mode="json") == payload, key.value


def test_every_template_parses_as_empty_document():
    for key in KnowledgeCategoryKey:
        text = (TEMPLATE_DIR / f"{key.value}.md").read_text(encoding="utf-8")
        document = parse_category_markdown(key, text, allow_empty=True)
        definition = category_contracts.get_category_definition(key)
        assert getattr(document, definition.list_field) == [], key.value
        template_questions = text.count("[")
        assert template_questions >= 1, f"{key.value} template lost its leading questions"


def test_table_fields_are_exactly_the_four_expected():
    found: set[str] = set()
    for key in KnowledgeCategoryKey:
        doc_model = CATEGORY_DOCUMENT_MODELS[key]
        definition = category_contracts.get_category_definition(key)
        record_model = _record_model(doc_model, definition.list_field)
        found |= {n for n, kind in _field_kinds(record_model).items() if kind == "table"}
    assert found == {"shifts", "stops", "allowances", "bonuses"}


def test_empty_document_round_trips():
    empty = {"schema_version": "1.0", "category": "jobs", "jobs": []}
    document = parse_category_markdown("jobs", build_source_markdown(empty), allow_empty=True)
    assert document.model_dump(mode="json") == empty


def test_bom_and_crlf_are_tolerated():
    payload = _payload("jobs")
    markdown = build_source_markdown(payload).replace("\n", "\r\n")
    document = parse_category_markdown("jobs", "﻿" + markdown)
    assert document.model_dump(mode="json") == payload


def test_html_comments_are_stripped():
    document = parse_category_markdown(
        "jobs",
        _JOBS_DOC_PREFIX + "<!-- hướng dẫn: điền dữ liệu -->\n",
        allow_empty=True,
    )
    assert document.jobs == []


def _rejects(source: str, message: str, key: str = "jobs") -> None:
    with pytest.raises(CategoryMarkdownError, match=message):
        parse_category_markdown(key, source)


def test_rejects_unknown_field():
    _rejects(_JOBS_DOC_PREFIX + '### record: a\ntitle: "X"\nbogus: 1\n', "unknown field 'bogus'")


def test_rejects_duplicate_field():
    _rejects(
        _JOBS_DOC_PREFIX + '### record: a\ntitle: "X"\ntitle: "Y"\n',
        "duplicate field 'title'",
    )


def test_rejects_duplicate_record_id():
    _rejects(
        _JOBS_DOC_PREFIX + '### record: a\ntitle: "X"\n### record: a\ntitle: "Y"\n',
        "duplicate record id 'a'",
    )


def test_rejects_missing_frontmatter():
    _rejects("## jobs\n", "must start with --- front-matter")


def test_rejects_wrong_category_key():
    _rejects(
        _JOBS_DOC_PREFIX.replace("category: jobs", "category: faq"),
        'front-matter category must be "jobs"',
    )


def test_rejects_wrong_schema_version():
    _rejects(
        _JOBS_DOC_PREFIX.replace('schema_version: "1.0"', 'schema_version: "2.0"'),
        'schema_version must be "1.0"',
    )


def test_rejects_unknown_frontmatter_key():
    _rejects(
        _JOBS_DOC_PREFIX.replace("---\n\n## jobs", "template: x\n---\n\n## jobs"),
        "unknown front-matter key",
    )


def test_rejects_unrecognized_line():
    _rejects(_JOBS_DOC_PREFIX + "### record: a\nvăn bản trôi nổi\n", "unrecognized line")


def test_rejects_nonempty_inline_list():
    _rejects(_JOBS_DOC_PREFIX + '### record: a\ntitle: "X"\naliases: [một, hai]\n', "inline lists")


def test_rejects_content_before_section():
    _rejects(
        _JOBS_DOC_PREFIX.replace("\n## jobs\n", "\nchào\n\n## jobs\n"),
        "expected the '## jobs' section heading first",
    )


def test_rejects_wrong_section_heading():
    _rejects(_JOBS_DOC_PREFIX.replace("## jobs", "## faq"), "section heading must be '## jobs'")


def test_rejects_list_item_without_open_field():
    _rejects(_JOBS_DOC_PREFIX + '### record: a\ntitle: "X"\n- rơi rơi\n', "without an open list")


def test_rejects_empty_scalar_value():
    _rejects(_JOBS_DOC_PREFIX + "### record: a\ntitle:\n", "needs a value")


def test_rejects_oversized_scalar():
    _rejects(_JOBS_DOC_PREFIX + '### record: a\ntitle: "' + "x" * 20_001 + '"\n', "character limit")


def test_rejects_wrong_table_columns():
    source = (
        "---\n"
        'schema_version: "1.0"\n'
        "category: work_schedules\n"
        "---\n"
        "\n"
        "## work_schedules\n"
        "\n"
        "### record: lich\n"
        "shifts:\n"
        "| name | start |\n"
        "| --- | --- |\n"
        "| Ca ngày | 07:30 |\n"
    )
    _rejects(source, "table columns must be", key="work_schedules")


def test_rejects_oversized_source():
    with pytest.raises(CategoryMarkdownError, match="500 KB limit"):
        parse_category_markdown("jobs", "---\n" + "x" * 500_001)
