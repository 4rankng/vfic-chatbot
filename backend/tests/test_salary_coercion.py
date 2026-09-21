"""Unit tests for salary coercion and salary-sort intent detection.

These cover the shapes that caused salaries to vanish in production:
LLM-returned numeric strings, seed-style small integers with a "triệu" unit
marker, and the Vietnamese phrasings candidates use to ask for salary ordering.
"""

from __future__ import annotations

from app.services.knowledge.derived_jobs import _coerce_salary_value, salary_from_feature


class TestCoerceSalaryValue:
    def test_python_int_passes_through(self) -> None:
        assert _coerce_salary_value(10_000_000) == 10_000_000

    def test_python_float_truncates_to_int(self) -> None:
        assert _coerce_salary_value(10_000_000.9) == 10_000_000

    def test_bool_is_rejected(self) -> None:
        # bool is an int subclass but is never a valid salary.
        assert _coerce_salary_value(True) is None
        assert _coerce_salary_value(False) is None

    def test_plain_numeric_string(self) -> None:
        assert _coerce_salary_value("10000000") == 10_000_000

    def test_dot_separated_thousands_string(self) -> None:
        # Vietnamese locale formatting: "10.000.000"
        assert _coerce_salary_value("10.000.000") == 10_000_000

    def test_comma_separated_thousands_string(self) -> None:
        assert _coerce_salary_value("10,000,000") == 10_000_000

    def test_currency_symbol_string(self) -> None:
        assert _coerce_salary_value("10000000₫") == 10_000_000

    def test_none_returns_none(self) -> None:
        assert _coerce_salary_value(None) is None

    def test_negative_rejected(self) -> None:
        assert _coerce_salary_value(-1000) is None

    def test_garbage_string_returns_none(self) -> None:
        assert _coerce_salary_value("thỏa thuận") is None

    def test_scale_applies_to_small_values_only(self) -> None:
        # Small int + triệu scale → VND
        assert _coerce_salary_value(7, scale=1_000_000) == 7_000_000
        # Large int + scale is left as-is (already VND)
        assert _coerce_salary_value(7_000_000, scale=1_000_000) == 7_000_000


class TestSalaryFromFeature:
    def test_canonical_vnd_ints(self) -> None:
        assert salary_from_feature(
            {"value_json": {"min": 10_000_000, "max": 13_000_000}}
        ) == (10_000_000, 13_000_000)

    def test_llm_numeric_strings(self) -> None:
        assert salary_from_feature(
            {"value_json": {"min": "10000000", "max": "13000000"}}
        ) == (10_000_000, 13_000_000)

    def test_llm_formatted_strings(self) -> None:
        assert salary_from_feature(
            {"value_json": {"min": "10.000.000", "max": "13.000.000"}}
        ) == (10_000_000, 13_000_000)

    def test_seed_style_small_ints_with_trieu_unit_scale(self) -> None:
        assert salary_from_feature(
            {"value_json": {"min": 7, "max": 12, "unit": "triệu VNĐ"}}
        ) == (7_000_000, 12_000_000)

    def test_unit_without_diacritics(self) -> None:
        assert salary_from_feature(
            {"value_json": {"min": 10, "max": 13, "unit": "trieu"}}
        ) == (10_000_000, 13_000_000)

    def test_million_unit(self) -> None:
        assert salary_from_feature(
            {"value_json": {"min": 10, "max": 13, "currency": "million VND"}}
        ) == (10_000_000, 13_000_000)

    def test_small_ints_without_unit_not_scaled(self) -> None:
        # Ambiguous — don't invent a scale when there's no unit marker.
        assert salary_from_feature({"value_json": {"min": 7, "max": 12}}) == (7, 12)

    def test_swapped_min_max_normalized(self) -> None:
        assert salary_from_feature(
            {"value_json": {"min": 13, "max": 10, "unit": "triệu"}}
        ) == (10_000_000, 13_000_000)

    def test_empty_dict(self) -> None:
        assert salary_from_feature({"value_json": {}}) == (None, None)

    def test_none_feature(self) -> None:
        assert salary_from_feature(None) == (None, None)

    def test_missing_value_json_key(self) -> None:
        assert salary_from_feature({}) == (None, None)

    def test_only_min_present(self) -> None:
        assert salary_from_feature({"value_json": {"min": 10_000_000}}) == (
            10_000_000,
            None,
        )

    def test_non_dict_value_json(self) -> None:
        assert salary_from_feature({"value_json": "not a dict"}) == (None, None)


# Sort-direction detection (salary/recency) moved to the Jev fan-out
# (``app.graph.decisions``, the ``sort_by`` judgment). The policy mapping is
# pinned in tests/test_graph_decisions.py; the phrase corpus that used to
# drive the keyword detector lives on as the opt-in live replay expectations
# in tests/test_golden_set.py.
