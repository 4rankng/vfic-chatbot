"""Invariants for the golden answer set (RAG pack B, tests/golden/answers.yaml).

The answer-gold set is the contract behind scripts/eval_answers.py and the
answer-quality release gate: expected answer points per question, abstention
entries for unanswerable questions, and a ref to the rag_gold case that
supplies its retrieval context. These tests keep the set consistent with the
rag_gold fixtures and pin the deterministic fact-hit scorer's semantics.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from tests.golden.answers import (
    AnswerGold,
    fact_hit_rate,
    load_answer_gold,
    normalize_text,
)
from tests.rag_gold.loader import load_cases

GOLD = load_answer_gold()
CASES_BY_ID = {case.id: case for case in load_cases()}


def test_gold_set_has_at_least_twenty_entries():
    assert len(GOLD) >= 20


def test_entry_ids_are_unique_and_populated():
    ids = [entry.id for entry in GOLD]
    assert len(ids) == len(set(ids))
    assert all(ids)


def test_every_entry_resolves_to_a_rag_gold_case():
    missing = [entry.id for entry in GOLD if entry.ref not in CASES_BY_ID]
    assert not missing, f"entries reference unknown rag_gold cases: {missing}"


def test_questions_match_the_referenced_gold_case_query():
    drift = [entry.id for entry in GOLD if CASES_BY_ID[entry.ref].query != entry.question]
    assert not drift, f"question text drifted from the rag_gold query: {drift}"


def test_non_abstain_entries_carry_expected_points():
    empty = [entry.id for entry in GOLD if not entry.abstain and not entry.expected_answer_points]
    assert not empty, f"entries without expected answer points: {empty}"


def test_abstain_entries_carry_no_expected_points():
    dirty = [entry.id for entry in GOLD if entry.abstain and entry.expected_answer_points]
    assert not dirty, f"abstain entries must not require answer points: {dirty}"


def test_gold_set_covers_required_categories():
    categories = {entry.category for entry in GOLD}
    required = {"salary", "overtime", "transport", "policy", "paraphrase", "abstention"}
    assert required.issubset(categories), f"missing categories: {required - categories}"


# ── normalize_text / fact_hit_rate semantics ──


def test_normalize_folds_diacritics_case_and_whitespace():
    assert normalize_text("  Sơ Yếu  Lý Lịch ") == "so yeu ly lich"
    assert normalize_text("SƠ YẾU LÝ LỊCH") == "so yeu ly lich"


def test_fact_hit_rate_full_hit():
    gold = AnswerGold("a", "salary", "ref", "q?", ("7.500.000", "800.000"))
    assert fact_hit_rate("Lương 7.500.000, phụ cấp 800.000.", gold) == 1.0


def test_fact_hit_rate_partial_hit():
    gold = AnswerGold("a", "salary", "ref", "q?", ("7.500.000", "800.000"))
    assert fact_hit_rate("Lương 7.500.000.", gold) == 0.5


def test_fact_hit_rate_matches_across_diacritics():
    gold = AnswerGold("a", "documents", "ref", "q?", ("Sơ yếu lý lịch",))
    assert fact_hit_rate("cần nộp so yeu ly lich và CCCD", gold) == 1.0


def test_fact_hit_rate_none_for_abstain_entries():
    gold = AnswerGold("a", "abstention", "ref", "q?", (), abstain=True)
    assert fact_hit_rate("em chưa có thông tin ạ", gold) is None


# ── loader validation ──


def _write(tmp_path: Path, entries: list[dict]) -> Path:
    path = tmp_path / "answers.yaml"
    path.write_text(yaml.safe_dump({"version": 1, "entries": entries}), encoding="utf-8")
    return path


def test_loader_rejects_duplicate_ids(tmp_path):
    entry = {
        "id": "x",
        "category": "salary",
        "ref": "r",
        "question": "q?",
        "expected_answer_points": ["1"],
    }
    with pytest.raises(ValueError, match="duplicate entry id"):
        load_answer_gold(_write(tmp_path, [entry, dict(entry)]))


def test_loader_rejects_abstain_with_points(tmp_path):
    path = _write(
        tmp_path,
        [
            {
                "id": "x",
                "category": "abstention",
                "ref": "r",
                "question": "q?",
                "expected_answer_points": ["1"],
                "abstain": True,
            }
        ],
    )
    with pytest.raises(ValueError, match="abstain entries must not carry"):
        load_answer_gold(path)


def test_loader_rejects_non_abstain_without_points(tmp_path):
    path = _write(
        tmp_path,
        [{"id": "x", "category": "salary", "ref": "r", "question": "q?", "expected_answer_points": []}],
    )
    with pytest.raises(ValueError, match="need expected_answer_points"):
        load_answer_gold(path)
