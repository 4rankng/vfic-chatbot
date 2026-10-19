"""Answer-quality release gate (RAG pack B): extraction + gating + CLI wiring.

The gate is REPORT-ONLY by default (release_gate_answer_quality_enabled=False)
so an uncalibrated metric can never block a deploy. These tests pin that
default, the blocking behavior once enabled, and the payload contract shared
with scripts/eval_answers.py --gate-output.
"""

from __future__ import annotations

import json
from argparse import Namespace
from types import SimpleNamespace

import pytest

from app.services.release_gate import (
    AnswerQualityError,
    AnswerQualityScores,
    evaluate_release_gate,
    extract_answer_quality,
)
from scripts import release_gate_check as cli

GOOD_PAYLOAD = {
    "schema": "answer-quality-gate/1",
    "fact_hit_rate": 0.95,
    "faithfulness": 0.90,
    "answer_relevancy": 0.85,
    "contextual_precision": 0.80,
    "contextual_recall": 0.90,
    "case_count": 39,
    "judged_cases": 39,
}


def _settings(**overrides) -> SimpleNamespace:
    defaults = {
        "release_gate_correctness_enabled": False,
        "release_gate_latency_slo_enabled": False,
        "release_gate_full_answer_p95_ms": 4000,
        "release_gate_error_rate_pct": 1.0,
        "release_gate_answer_quality_enabled": False,
        "release_gate_fact_hit_rate_min": 0.80,
        "release_gate_faithfulness_min": 0.75,
        "release_gate_answer_relevancy_min": 0.70,
        "release_gate_contextual_precision_min": 0.60,
        "release_gate_contextual_recall_min": 0.70,
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


# ── extraction ──


def test_extract_answer_quality_reads_all_five_metrics():
    scores = extract_answer_quality(GOOD_PAYLOAD)
    assert scores.fact_hit_rate == 0.95
    assert scores.faithfulness == 0.90
    assert scores.as_dict()["contextual_recall"] == 0.90


def test_extract_answer_quality_rejects_missing_metrics():
    partial = {k: v for k, v in GOOD_PAYLOAD.items() if k != "faithfulness"}
    with pytest.raises(AnswerQualityError, match="missing metrics: faithfulness"):
        extract_answer_quality(partial)


def test_extract_answer_quality_rejects_out_of_range():
    bad = dict(GOOD_PAYLOAD, faithfulness=1.5)
    with pytest.raises(AnswerQualityError, match="ratio between 0 and 1"):
        extract_answer_quality(bad)


def test_extract_answer_quality_rejects_non_numbers():
    bad = dict(GOOD_PAYLOAD, fact_hit_rate="0.9")
    with pytest.raises(AnswerQualityError, match="JSON number"):
        extract_answer_quality(bad)


# ── gating ──


async def test_gate_is_report_only_by_default():
    scores = extract_answer_quality(GOOD_PAYLOAD)
    result = await evaluate_release_gate(
        db=None,
        settings=_settings(),
        golden_pass_rate=98.0,
        answer_quality=scores,
    )
    assert result.passed
    assert "answer_quality" in result.not_evaluated
    assert result.answer_quality == scores  # surfaced, never blocking


async def test_gate_blocks_when_enabled_and_payload_missing():
    result = await evaluate_release_gate(
        db=None,
        settings=_settings(release_gate_answer_quality_enabled=True),
        golden_pass_rate=98.0,
        answer_quality=None,
    )
    assert not result.passed
    assert any(f.gate == "answer_quality" and "payload missing" in f.detail for f in result.failures)


async def test_gate_blocks_on_metric_below_threshold():
    scores = AnswerQualityScores(
        fact_hit_rate=0.95,
        faithfulness=0.50,  # below release_gate_faithfulness_min
        answer_relevancy=0.85,
        contextual_precision=0.80,
        contextual_recall=0.90,
    )
    result = await evaluate_release_gate(
        db=None,
        settings=_settings(release_gate_answer_quality_enabled=True),
        golden_pass_rate=98.0,
        answer_quality=scores,
    )
    assert not result.passed
    failing = [f for f in result.failures if f.gate == "answer_quality.faithfulness"]
    assert failing and failing[0].actual == 0.50 and failing[0].threshold == 0.75


async def test_gate_passes_when_enabled_and_scores_meet_thresholds():
    result = await evaluate_release_gate(
        db=None,
        settings=_settings(release_gate_answer_quality_enabled=True),
        golden_pass_rate=98.0,
        answer_quality=extract_answer_quality(GOOD_PAYLOAD),
    )
    assert result.passed
    assert not [f for f in result.failures if f.gate.startswith("answer_quality")]
    assert "answer_quality" not in result.not_evaluated


# ── CLI wiring ──


def _cli_settings(**overrides) -> SimpleNamespace:
    return _settings(**overrides)


class _ForbiddenSessionFactory:
    def __call__(self):
        raise AssertionError("async_session should not be used")


async def test_cli_prints_scores_in_report_only_mode(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(cli, "get_settings", lambda: _cli_settings())
    monkeypatch.setattr(cli, "async_session", _ForbiddenSessionFactory())
    payload = tmp_path / "answer-quality.json"
    payload.write_text(json.dumps(GOOD_PAYLOAD), encoding="utf-8")

    rc = await cli._run(
        Namespace(golden_results=None, answer_quality=payload, window_hours=24)
    )

    captured = capsys.readouterr()
    assert rc == 0
    assert "answer quality (report-only):" in captured.out
    assert "faithfulness=0.900" in captured.out


async def test_cli_requires_payload_when_gate_enabled(monkeypatch, capsys):
    monkeypatch.setattr(
        cli,
        "get_settings",
        lambda: _cli_settings(release_gate_answer_quality_enabled=True),
    )
    monkeypatch.setattr(cli, "async_session", _ForbiddenSessionFactory())

    rc = await cli._run(
        Namespace(golden_results=None, answer_quality=None, window_hours=24)
    )

    captured = capsys.readouterr()
    assert rc == 1
    assert "--answer-quality is required" in captured.err


async def test_cli_blocks_on_malformed_payload(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(cli, "get_settings", lambda: _cli_settings())
    monkeypatch.setattr(cli, "async_session", _ForbiddenSessionFactory())
    payload = tmp_path / "answer-quality.json"
    payload.write_text(json.dumps({"fact_hit_rate": 0.9}), encoding="utf-8")

    rc = await cli._run(
        Namespace(golden_results=None, answer_quality=payload, window_hours=24)
    )

    assert rc == 1
    assert "missing metrics" in capsys.readouterr().err
