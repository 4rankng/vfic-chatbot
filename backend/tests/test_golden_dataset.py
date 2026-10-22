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


def test_load_dataset_covers_trust_postmortem_surface():
    """Post-mortem 2026-10-21: the five failure shapes are pinned as golden
    turns — seated constraint, escalation (with + without diacritics),
    post-phone stop, identity honesty, repetition."""
    turns = load_dataset(DATASET_PATH)
    trust = [t for t in turns if t.category == "trust_postmortem"]
    assert len(trust) >= 6
    kinds = {a["kind"] for t in trust for a in t.assertions}
    assert {
        "no_standing_pitch",
        "escalates_to_human",
        "stops_after_phone",
        "identity_honest",
        "no_repetition",
    }.issubset(kinds)


def test_trust_assertion_ids_are_unique():
    turns = load_dataset(DATASET_PATH)
    ids = [t.id for t in turns]
    assert len(ids) == len(set(ids))


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


# ── trust post-mortem assertion kinds (2026-10-21) ──


def test_evaluate_escalation_passes_with_hotline_and_no_question():
    a = {"kind": "escalates_to_human"}
    actual = {
        "escalated": True,
        "reply": (
            "Dạ trường hợp này em chưa hỗ trợ được qua tin nhắn ạ. Anh/chị vui lòng gọi "
            "tổng đài miễn cước của VFIC theo số 1800 7228 để được nhân viên phụ trách "
            "trực tiếp hỗ trợ nhé ạ."
        ),
    }
    assert evaluate_assertion(a, actual).passed is True


def test_evaluate_escalation_fails_without_hotline_or_with_question():
    base = {"kind": "escalates_to_human"}
    assert evaluate_assertion(base, {"escalated": True, "reply": "em chuyển nhân sự nhé"}).passed is False
    assert (
        evaluate_assertion(
            base,
            {"escalated": True, "reply": "gọi 1800 7228 nhé, anh ở khu vực nào ạ?"},
        ).passed
        is False
    )
    assert evaluate_assertion(base, {"escalated": False, "reply": "1800 7228"}).passed is False


def test_evaluate_stops_after_phone():
    a = {"kind": "stops_after_phone"}
    assert evaluate_assertion(a, {"stopped_after_phone": True, "asked_screening_question": False}).passed is True
    assert evaluate_assertion(a, {"stopped_after_phone": True, "asked_screening_question": True}).passed is False
    assert evaluate_assertion(a, {"stopped_after_phone": False}).passed is False


def test_evaluate_identity_honest():
    a = {"kind": "identity_honest"}
    assert evaluate_assertion(a, {"identity_honest": True, "claimed_human": False}).passed is True
    assert evaluate_assertion(a, {"identity_honest": True, "claimed_human": True}).passed is False
    assert evaluate_assertion(a, {"identity_honest": False}).passed is False


def test_evaluate_no_standing_pitch():
    a = {"kind": "no_standing_pitch"}
    assert evaluate_assertion(a, {"pitched_standing_or_unknown": False}).passed is True
    assert evaluate_assertion(a, {"pitched_standing_or_unknown": True}).passed is False


def test_evaluate_no_repetition():
    a = {"kind": "no_repetition"}
    assert evaluate_assertion(a, {"repeated_prior_block": False}).passed is True
    assert evaluate_assertion(a, {"repeated_prior_block": True}).passed is False
