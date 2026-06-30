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
