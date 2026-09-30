"""RAG benchmark fixture contract tests."""

from __future__ import annotations

import json

import pytest


def test_load_cases_validates_fixture_shape(tmp_path):
    from scripts.benchmark_rag import _load_cases

    fixture = tmp_path / "rag_cases.json"
    fixture.write_text(
        json.dumps(
            [
                {
                    "id": "case_a",
                    "query": "Lương LG Display bao nhiêu?",
                    "project_slug": "lg-display",
                    "expected_terms": ["lương", "LG Display"],
                    "forbidden_terms": ["Samsung"],
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    cases = _load_cases(fixture)

    assert len(cases) == 1
    assert cases[0].id == "case_a"
    assert cases[0].expected_terms == ["lương", "LG Display"]


def test_load_cases_rejects_missing_expected_terms(tmp_path):
    from scripts.benchmark_rag import _load_cases

    fixture = tmp_path / "rag_cases.json"
    fixture.write_text(json.dumps([{"query": "hello"}]), encoding="utf-8")

    with pytest.raises(ValueError, match="expected_terms"):
        _load_cases(fixture)


def test_gate_output_is_a_single_pass_rate_source_for_the_release_gate(tmp_path):
    """The gate file must satisfy extract_golden_pass_rate's single-source rule.

    The raw --output artifact carries pass_rate AND passed/case_count, which
    the release gate rejects as ambiguous ("multiple pass-rate sources"), so
    --gate-output writes exactly one source instead.
    """
    from app.services.release_gate import GoldenResultsError, extract_golden_pass_rate
    from scripts.benchmark_rag import _write_gate_output

    gate_file = tmp_path / "golden.json"
    _write_gate_output(gate_file, 0.875)

    payload = json.loads(gate_file.read_text(encoding="utf-8"))
    assert payload == {"golden_pass_rate_pct": 87.5}
    assert extract_golden_pass_rate(payload) == 87.5

    with pytest.raises(GoldenResultsError, match="multiple pass-rate sources"):
        extract_golden_pass_rate(
            {"golden_pass_rate_pct": 87.5, "passed": 7, "case_count": 8}
        )
