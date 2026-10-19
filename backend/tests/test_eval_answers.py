"""Tests for scripts/eval_answers.py — answer-quality harness (RAG pack B).

Pure aggregation/decision logic + offline CLI paths (retrieval over the canned
rag_gold fixtures, replayed answers). No LLM, no network, no deepeval import:
the judge layer is exercised only when the app provider is configured (the
P3-2 evidence run recorded in docs/decisions/0014-*).
"""

from __future__ import annotations

import json

from scripts.eval_answers import (
    COMPARISON_SCHEMA,
    REPORT_SCHEMA,
    aggregate_case_scores,
    build_gate_payload,
    compare_runs,
    format_comparison,
    load_gold_bundle,
    main,
)


def _case(case_id: str, **overrides) -> dict:
    case = {
        "id": case_id,
        "precision_at_3": 1.0,
        "precision_at_5": 1.0,
        "recall_at_10": 1.0,
        "mrr": 1.0,
        "fact_hit_rate": 1.0,
        "answer": "ok",
        "judge": None,
        "errors": [],
    }
    case.update(overrides)
    return case


# ── aggregation ──


def test_aggregate_case_scores_means_and_counts():
    cases = [
        _case("a", fact_hit_rate=1.0),
        _case("b", fact_hit_rate=0.5, judge={"faithfulness": 0.8}),
        _case("c", fact_hit_rate=None, answer=None, errors=["generation: boom"]),
    ]
    agg = aggregate_case_scores(cases)
    assert agg["case_count"] == 3
    assert agg["answered_cases"] == 2
    assert agg["judged_cases"] == 1
    assert agg["errored_cases"] == 1
    assert agg["fact_hit_rate"] == 0.75
    assert agg["faithfulness"] == 0.8
    assert agg["answer_relevancy"] is None


def test_aggregate_of_no_judge_run_has_null_judge_metrics():
    agg = aggregate_case_scores([_case("a")])
    assert agg["faithfulness"] is None
    assert agg["judged_cases"] == 0


# ── gate payload ──


def _report_with_judge() -> dict:
    cases = [
        _case(
            "a",
            judge={
                "faithfulness": 0.9,
                "answer_relevancy": 0.8,
                "contextual_precision": 0.7,
                "contextual_recall": 0.6,
            },
        )
    ]
    return {"schema": REPORT_SCHEMA, "config": {"rag_rerank_enabled": False}, "cases": cases, "aggregate": aggregate_case_scores(cases)}


def test_build_gate_payload_with_judge_scores():
    payload = build_gate_payload(_report_with_judge())
    assert payload is not None
    assert payload["fact_hit_rate"] == 1.0
    assert payload["faithfulness"] == 0.9
    assert payload["contextual_recall"] == 0.6
    assert payload["case_count"] == 1


def test_build_gate_payload_refuses_partial_metrics():
    report = {"aggregate": {"fact_hit_rate": 0.9, "faithfulness": 0.8, "case_count": 3}}
    assert build_gate_payload(report) is None


# ── P3-2 comparison + decision ──


def test_compare_runs_precision_lift_at_rule_boundary_enables():
    off = {"aggregate": {"mean_precision_at_3": 0.500}}
    on = {"aggregate": {"mean_precision_at_3": 0.520}}
    comparison = compare_runs(off, on)
    assert comparison["precision_lift_points"] == 2.0
    assert comparison["enable_rerank"] is True


def test_compare_runs_below_rule_keeps_rerank_off():
    off = {"aggregate": {"mean_precision_at_3": 0.500}}
    on = {"aggregate": {"mean_precision_at_3": 0.519}}
    comparison = compare_runs(off, on)
    assert comparison["precision_lift_points"] == 1.9
    assert comparison["enable_rerank"] is False
    assert "keep rag_rerank_enabled off" in comparison["detail"]


def test_compare_runs_reports_judge_metrics_as_evidence():
    off = {
        "aggregate": {
            "mean_precision_at_3": 0.5,
            "faithfulness": 0.8,
            "fact_hit_rate": 0.9,
        }
    }
    on = {
        "aggregate": {
            "mean_precision_at_3": 0.5,
            "faithfulness": 0.85,
            "fact_hit_rate": 0.95,
        }
    }
    comparison = compare_runs(off, on)
    assert comparison["metrics"]["faithfulness"] == {
        "off": 0.8,
        "on": 0.85,
        "lift_points": 5.0,
    }
    assert comparison["enable_rerank"] is False


def test_compare_runs_without_precision_makes_no_decision():
    comparison = compare_runs({"aggregate": {}}, {"aggregate": {}})
    assert comparison["precision_lift_points"] is None
    assert comparison["enable_rerank"] is False
    assert "no decision" in comparison["detail"]


def test_format_comparison_contains_table_and_decision():
    comparison = compare_runs(
        {"aggregate": {"mean_precision_at_3": 0.5, "fact_hit_rate": 0.9}},
        {"aggregate": {"mean_precision_at_3": 0.5, "fact_hit_rate": 0.9}},
    )
    text = format_comparison(comparison)
    assert "mean_precision_at_3" in text
    assert "fact_hit_rate" in text
    assert "decision:" in text


# ── offline CLI paths ──


def test_cli_retrieval_only_run_scores_both_configs(tmp_path, capsys):
    out = tmp_path / "report.json"
    rc = main(
        [
            "--rerank",
            "both",
            "--no-answers",
            "--max-cases",
            "3",
            "--output",
            str(out),
        ]
    )
    assert rc == 0
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["schema"] == COMPARISON_SCHEMA
    for side in ("off", "on"):
        assert payload[side]["config"]["answers"] == "none"
        assert payload[side]["aggregate"]["case_count"] == 3
        assert payload[side]["aggregate"]["mean_precision_at_3"] is not None
        assert payload[side]["aggregate"]["faithfulness"] is None
    assert "decision:" in capsys.readouterr().out
    assert "mean_precision_at_3" in payload["comparison"]["metrics"]


def test_cli_replay_scores_recorded_answers_offline(tmp_path, capsys):
    bundle = load_gold_bundle()
    entries = list(bundle.entries)[:4]
    assert all(not e.abstain for e in entries)
    replay = {
        "schema": REPORT_SCHEMA,
        "cases": [
            {"id": e.id, "answer": f"Trả lời: {'; '.join(e.expected_answer_points)}"}
            for e in entries
        ],
    }
    replay_path = tmp_path / "replay.json"
    replay_path.write_text(json.dumps(replay), encoding="utf-8")
    out = tmp_path / "report.json"

    rc = main(
        [
            "--rerank",
            "off",
            "--replay",
            str(replay_path),
            "--judge",
            "off",
            "--max-cases",
            "4",
            "--output",
            str(out),
        ]
    )
    assert rc == 0
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["config"]["answers"] == "replay"
    assert payload["aggregate"]["fact_hit_rate"] == 1.0
    assert payload["aggregate"]["judged_cases"] == 0


def test_cli_gate_output_skipped_without_judge_metrics(tmp_path, capsys):
    gate_out = tmp_path / "gate.json"
    rc = main(
        [
            "--rerank",
            "off",
            "--no-answers",
            "--max-cases",
            "2",
            "--gate-output",
            str(gate_out),
        ]
    )
    assert rc == 0
    assert not gate_out.exists()
    assert "gate-output skipped" in capsys.readouterr().err


def test_cli_replay_without_recorded_answer_reports_error(tmp_path):
    bundle = load_gold_bundle()
    entries = [e for e in bundle.entries if not e.abstain][:2]
    first, second = entries
    replay_path = tmp_path / "replay.json"
    replay_path.write_text(
        json.dumps(
            {
                "schema": REPORT_SCHEMA,
                "cases": [
                    {"id": first.id, "answer": f"Trả lời: {'; '.join(first.expected_answer_points)}"},
                    {"id": "some-other-id", "answer": "x"},
                ],
            }
        ),
        encoding="utf-8",
    )
    out = tmp_path / "report.json"
    rc = main(
        [
            "--rerank",
            "off",
            "--replay",
            str(replay_path),
            "--judge",
            "off",
            "--max-cases",
            "2",
            "--output",
            str(out),
        ]
    )
    assert rc == 0
    payload = json.loads(out.read_text(encoding="utf-8"))
    by_id = {c["id"]: c for c in payload["cases"]}
    assert by_id[first.id]["answer"] is not None
    missing = by_id[second.id]
    assert missing["answer"] is None
    assert any("replay: no recorded answer" in e for e in missing["errors"])
