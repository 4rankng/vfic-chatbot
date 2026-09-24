"""Tests for the release-gate evaluator (P3-3)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services.release_gate import (
    GoldenResultsError,
    evaluate_release_gate,
    extract_golden_pass_rate,
)


def _settings(**overrides) -> SimpleNamespace:
    defaults = {
        "release_gate_correctness_enabled": True,
        "release_gate_latency_slo_enabled": True,
        "release_gate_full_answer_p95_ms": 4000,
        "release_gate_error_rate_pct": 1.0,
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _patch_window_count(monkeypatch, n: int = 10_000) -> None:
    """Pretend the SLO window has ample measurements so SLO gates engage."""
    from app.services import release_gate

    async def fake_count(db, interval, **_kwargs):
        return n

    monkeypatch.setattr(release_gate, "count_measured_runs", fake_count)


async def test_release_gate_passes_when_all_green(monkeypatch):
    from app.services import release_gate, slo_service

    async def fake_slos(db, interval, **_kwargs):
        return [
            slo_service.SloResult("full_answer", "", 4000, "ms", 2000, 3500, "green"),
            slo_service.SloResult("error_or_timeout_rate", "", 1.0, "%", 0.5, 0.5, "green"),
        ]

    monkeypatch.setattr(release_gate, "compute_slos", fake_slos)
    _patch_window_count(monkeypatch)
    result = await evaluate_release_gate(
        db=None, settings=_settings(), golden_pass_rate=98.0
    )
    assert result.verdict == "pass"
    assert result.failures == []


async def test_release_gate_passes_at_exact_threshold(monkeypatch):
    from app.services import release_gate

    async def fake_slos(db, interval, **_kwargs):
        return []

    monkeypatch.setattr(release_gate, "compute_slos", fake_slos)
    result = await evaluate_release_gate(
        db=None,
        settings=_settings(release_gate_latency_slo_enabled=False),
        golden_pass_rate=95.0,
    )
    assert result.verdict == "pass"


async def test_release_gate_blocks_on_correctness_regression(monkeypatch):
    """Golden pass-rate below 95% blocks deploy."""
    from app.services import release_gate, slo_service

    async def fake_slos(db, interval, **_kwargs):
        return [
            slo_service.SloResult("full_answer", "", 4000, "ms", 2000, 3500, "green"),
            slo_service.SloResult("error_or_timeout_rate", "", 1.0, "%", 0.5, 0.5, "green"),
        ]

    monkeypatch.setattr(release_gate, "compute_slos", fake_slos)
    _patch_window_count(monkeypatch)
    result = await evaluate_release_gate(
        db=None, settings=_settings(), golden_pass_rate=80.0  # below 95%
    )
    assert result.verdict == "block"
    assert any(f.gate == "retrieval_correctness" for f in result.failures)


async def test_release_gate_blocks_on_latency_regression(monkeypatch):
    """full_answer p95 above the threshold blocks deploy."""
    from app.services import release_gate, slo_service

    async def fake_slos(db, interval, **_kwargs):
        return [
            slo_service.SloResult("full_answer", "", 4000, "ms", 3000, 5500, "red"),
            slo_service.SloResult("error_or_timeout_rate", "", 1.0, "%", 0.5, 0.5, "green"),
        ]

    monkeypatch.setattr(release_gate, "compute_slos", fake_slos)
    _patch_window_count(monkeypatch)
    result = await evaluate_release_gate(
        db=None, settings=_settings(), golden_pass_rate=98.0
    )
    assert result.verdict == "block"
    assert any(f.gate == "full_answer_p95" for f in result.failures)


async def test_release_gate_blocks_on_error_rate_regression(monkeypatch):
    from app.services import release_gate, slo_service

    async def fake_slos(db, interval, **_kwargs):
        return [
            slo_service.SloResult("full_answer", "", 4000, "ms", 2000, 3500, "green"),
            slo_service.SloResult("error_or_timeout_rate", "", 1.0, "%", 3.0, 3.0, "red"),
        ]

    monkeypatch.setattr(release_gate, "compute_slos", fake_slos)
    _patch_window_count(monkeypatch)
    result = await evaluate_release_gate(
        db=None, settings=_settings(), golden_pass_rate=98.0
    )
    assert result.verdict == "block"
    assert any(f.gate == "error_rate" for f in result.failures)


async def test_release_gate_skips_slo_gate_when_window_data_is_insufficient(monkeypatch):
    """A tiny SLO window (e.g. 2 overnight runs, both errors) is sample-size noise.

    Rate/latency SLOs over < MIN_WINDOW_RUNS measurements must not block the
    release; they surface as not-evaluated instead. The golden correctness
    gate still gates.
    """
    from app.services import release_gate, slo_service

    async def fake_slos(db, interval, **_kwargs):
        return [
            slo_service.SloResult("full_answer", "", 4000, "ms", 8000, 9157, "red"),
            slo_service.SloResult("error_or_timeout_rate", "", 1.0, "%", 100.0, 100.0, "red"),
        ]

    async def fake_count(db, interval, **_kwargs):
        return 2

    monkeypatch.setattr(release_gate, "compute_slos", fake_slos)
    monkeypatch.setattr(release_gate, "count_measured_runs", fake_count)
    result = await evaluate_release_gate(
        db=None, settings=_settings(), golden_pass_rate=98.0
    )
    assert result.verdict == "pass"
    assert result.failures == []
    assert any("insufficient window data" in note for note in result.not_evaluated)


async def test_release_gate_blocks_on_slo_regression_with_sufficient_window(monkeypatch):
    """With >= MIN_WINDOW_RUNS measurements, SLO breaches still block (fail-closed kept)."""
    from app.services import release_gate, slo_service

    async def fake_slos(db, interval, **_kwargs):
        return [
            slo_service.SloResult("full_answer", "", 4000, "ms", 8000, 9157, "red"),
            slo_service.SloResult("error_or_timeout_rate", "", 1.0, "%", 100.0, 100.0, "red"),
        ]

    async def fake_count(db, interval, **_kwargs):
        return 50

    monkeypatch.setattr(release_gate, "compute_slos", fake_slos)
    monkeypatch.setattr(release_gate, "count_measured_runs", fake_count)
    result = await evaluate_release_gate(
        db=None, settings=_settings(), golden_pass_rate=98.0
    )
    assert result.verdict == "block"
    assert {f.gate for f in result.failures} == {"full_answer_p95", "error_rate"}


async def test_release_gate_skip_when_gates_disabled(monkeypatch):
    """When both gates are disabled, the verdict is always pass."""
    from app.services import release_gate

    async def fake_slos(db, interval, **_kwargs):
        raise AssertionError("compute_slos should not run when latency gates are disabled")

    monkeypatch.setattr(release_gate, "compute_slos", fake_slos)
    s = _settings(release_gate_correctness_enabled=False, release_gate_latency_slo_enabled=False)
    result = await evaluate_release_gate(db=None, settings=s, golden_pass_rate=10.0)
    assert result.verdict == "pass"
    assert result.slos == []
    assert set(result.not_evaluated) == {"retrieval_correctness", "latency_slo"}


async def test_release_gate_blocks_when_golden_pass_rate_is_missing(monkeypatch):
    """Correctness-enabled releases must fail closed without golden results."""
    from app.services import release_gate, slo_service

    async def fake_slos(db, interval, **_kwargs):
        return [
            slo_service.SloResult("full_answer", "", 4000, "ms", 2000, 3500, "green"),
        ]

    monkeypatch.setattr(release_gate, "compute_slos", fake_slos)
    _patch_window_count(monkeypatch)
    result = await evaluate_release_gate(db=None, settings=_settings(), golden_pass_rate=None)
    assert result.verdict == "block"
    assert any(f.gate == "retrieval_correctness" for f in result.failures)


async def test_release_gate_blocks_when_latency_measurements_are_missing(monkeypatch):
    from app.services import release_gate

    async def fake_slos(db, interval, **_kwargs):
        return []

    monkeypatch.setattr(release_gate, "compute_slos", fake_slos)
    _patch_window_count(monkeypatch)
    result = await evaluate_release_gate(db=None, settings=_settings(), golden_pass_rate=100.0)
    assert result.verdict == "block"
    assert {failure.gate for failure in result.failures} == {"full_answer_p95", "error_rate"}


async def test_release_gate_rejects_non_positive_window(monkeypatch):
    from app.services import release_gate

    async def fake_slos(db, interval, **_kwargs):
        raise AssertionError("compute_slos should not run for invalid windows")

    monkeypatch.setattr(release_gate, "compute_slos", fake_slos)
    with pytest.raises(ValueError, match="window_hours must be greater than zero"):
        await evaluate_release_gate(
            db=None,
            settings=_settings(release_gate_latency_slo_enabled=False),
            golden_pass_rate=100.0,
            window_hours=0,
        )


def test_extract_golden_pass_rate_accepts_ratio_payload():
    assert extract_golden_pass_rate({"pass_rate": 0.98}) == 98.0


def test_extract_golden_pass_rate_accepts_percentage_payload():
    assert extract_golden_pass_rate({"golden_pass_rate_pct": 98.0}) == 98.0


def test_extract_golden_pass_rate_derives_from_pass_counts():
    assert extract_golden_pass_rate({"passed": 47, "case_count": 50}) == 94.0


def test_extract_golden_pass_rate_rejects_missing_fields():
    with pytest.raises(GoldenResultsError):
        extract_golden_pass_rate({"results": []})


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ({"golden_pass_rate": 98.0}, "ambiguous"),
        ({"pass_rate": True}, "boolean"),
        ({"pass_rate": "0.98"}, "JSON number"),
        ({"pass_rate": 98.0}, "ratio"),
        ({"golden_pass_rate_pct": 1.2, "pass_rate": 0.012}, "multiple"),
        ({"golden_pass_rate_pct": "98"}, "JSON number"),
        ({"golden_pass_rate_pct": 120.0}, "between 0 and 100"),
        ({"passed": 1.0, "case_count": 2}, "integer"),
        ({"passed": -1, "case_count": 2}, "non-negative"),
        ({"passed": 3, "case_count": 2}, "less than or equal"),
        ({"passed": 1}, "provided together"),
        ({"case_count": 2}, "provided together"),
    ],
)
def test_extract_golden_pass_rate_rejects_invalid_payloads(payload, message):
    with pytest.raises(GoldenResultsError, match=message):
        extract_golden_pass_rate(payload)


async def test_release_gate_ignores_synthetic_seed_telemetry(monkeypatch):
    """A seeded local DB must not block a release.

    ``make seed`` writes demo telemetry (stage_timings.synthetic) into bot_runs
    for the performance dashboard. The gate must ask the SLO queries to exclude
    it — otherwise any seeded machine reports the seed's "critical" turns as a
    p95/error-rate breach.
    """
    from app.services import release_gate

    seen: dict[str, dict] = {}

    async def fake_slos(db, interval, **kwargs):
        seen["slos"] = kwargs
        return []

    async def fake_count(db, interval, **kwargs):
        seen["count"] = kwargs
        return 10_000

    monkeypatch.setattr(release_gate, "compute_slos", fake_slos)
    monkeypatch.setattr(release_gate, "count_measured_runs", fake_count)

    await evaluate_release_gate(db=None, settings=_settings(), golden_pass_rate=98.0)

    assert seen["slos"] == {"exclude_synthetic": True}
    assert seen["count"] == {"exclude_synthetic": True}
