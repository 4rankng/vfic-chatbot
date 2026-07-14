"""Tests for the golden dataset loader + assertion evaluator (P3-1)."""

from __future__ import annotations

from pathlib import Path


from tests.golden.runner import (
    GoldenTurn,
    evaluate_assertion,
    load_dataset,
)


DATASET_PATH = Path(__file__).parent / "golden" / "dataset.yaml"


def test_load_dataset_returns_turns():
    turns = load_dataset(DATASET_PATH)
    assert len(turns) >= 10
    assert all(isinstance(t, GoldenTurn) for t in turns)


def test_load_dataset_each_turn_has_required_fields():
    turns = load_dataset(DATASET_PATH)
    for t in turns:
        assert t.id
        assert t.category
        assert t.input
        assert isinstance(t.assertions, list)


def test_load_dataset_covers_directive_categories():
    """Directive §2.8: job-detail, bus, benefit, compare, recommend, multi-turn,
    paraphrase, edge cases, safety."""
    turns = load_dataset(DATASET_PATH)
    categories = {t.category for t in turns}
    required = {"job_detail", "bus_schedule", "benefits", "paraphrase", "recommendation", "safety"}
    assert required.issubset(categories), f"missing categories: {required - categories}"


def test_evaluate_assertion_intent_match():
    a = {"kind": "intent", "value": "job_lookup"}
    actual = {"intent": "job_lookup"}
    r = evaluate_assertion(a, actual)
    assert r.passed is True


def test_evaluate_assertion_intent_mismatch():
    a = {"kind": "intent", "value": "job_lookup"}
    actual = {"intent": "faq_lookup"}
    r = evaluate_assertion(a, actual)
    assert r.passed is False
    assert "faq_lookup" in r.detail


def test_evaluate_assertion_no_hallucination_passes_when_clean():
    a = {"kind": "no_hallucination"}
    actual = {"hallucinated": False}
    assert evaluate_assertion(a, actual).passed is True


def test_evaluate_assertion_no_hallucination_fails_when_hallucinated():
    a = {"kind": "no_hallucination"}
    actual = {"hallucinated": True}
    assert evaluate_assertion(a, actual).passed is False


def test_evaluate_assertion_latency_under_threshold():
    a = {"kind": "latency_p95_below_ms", "value": 4000}
    actual = {"latency_ms": 3500}
    assert evaluate_assertion(a, actual).passed is True


def test_evaluate_assertion_latency_over_threshold():
    a = {"kind": "latency_p95_below_ms", "value": 4000}
    actual = {"latency_ms": 5000}
    assert evaluate_assertion(a, actual).passed is False


def test_evaluate_assertion_unknown_kind_fails():
    a = {"kind": "nonexistent", "value": "x"}
    r = evaluate_assertion(a, {})
    assert r.passed is False
    assert "unknown" in r.detail.lower()
