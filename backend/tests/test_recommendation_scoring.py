"""Tests for the pure salary-parsing policies shared by the matchers.

``parse_salary_band`` feeds the salary fit dimension and the income tools;
``is_salary_profile_statement`` keeps first-person salary declarations out of
cross-project income comparisons. Both are pure Python (no DB, no LLM).
"""

from __future__ import annotations

from app.recruitment.domain.recommendation import (
    is_salary_profile_statement,
    parse_salary_band,
)


def test_parse_salary_band_single_trieu():
    assert parse_salary_band("12 triệu") == (9_600_000, 12_000_000)


def test_parse_salary_band_range_trieu():
    assert parse_salary_band("10-15 triệu") == (10_000_000, 15_000_000)


def test_parse_salary_band_plain_vnd():
    lo, hi = parse_salary_band("20000000")
    assert lo == 16_000_000
    assert hi == 20_000_000


def test_parse_salary_band_accented_vietnamese():
    # normalize_vietnamese_text strips diacritics before matching.
    assert parse_salary_band("12 triệu") == (9_600_000, 12_000_000)


def test_parse_salary_band_none_when_unparseable():
    assert parse_salary_band(None) == (None, None)
    assert parse_salary_band("") == (None, None)
    assert parse_salary_band("thỏa thuận") == (None, None)
    assert parse_salary_band(f"{'9' * 400} triệu") == (None, None)


def test_salary_profile_statement_is_not_a_project_comparison():
    statements = (
        "Lương mong muốn của em là 20 triệu",
        "Em đang nhận lương 20 triệu",
        "Thu nhập hiện tại của em là 15 triệu",
    )

    assert all(is_salary_profile_statement(text) for text in statements)
