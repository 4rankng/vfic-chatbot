"""Salary bands must keep their real figures and never render as "7-7"."""

import pytest

from app.graph.tools import format_salary_range


@pytest.mark.parametrize(
    ("minimum", "maximum", "expected"),
    [
        # The production LG Display row. Integer division truncated both bounds
        # to 7 and emitted "lương 7-7 triệu", losing the range and the amount.
        (7_430_000, 7_930_000, "lương 7,4-7,9 triệu"),
        (14_000_000, 15_000_000, "lương 14-15 triệu"),
        # A genuinely single value still collapses rather than repeating itself.
        (7_000_000, 7_000_000, "lương 7 triệu"),
        (7_430_000, 7_430_000, "lương 7,4 triệu"),
        (10_000_000, None, "lương từ 10 triệu"),
        (None, 12_500_000, "lương đến 12,5 triệu"),
        (None, None, ""),
    ],
)
def test_format_salary_range(minimum, maximum, expected):
    assert format_salary_range(minimum, maximum) == expected
