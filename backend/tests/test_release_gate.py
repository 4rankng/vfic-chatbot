"""Tests for the release-gate evaluator (P3-3)."""

from __future__ import annotations

from types import SimpleNamespace


from app.services.release_gate import (
    evaluate_release_gate,
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


async def test_release_gate_passes_when_all_green(monkeypatch):
    from app.services import release_gate, slo_service

    async def fake_slos(db, interval):
        return [
            slo_service.SloResult("full_answer", "", 4000, "ms", 2000, 3500, "green"),
            slo_service.SloResult("error_or_timeout_rate", "", 1.0, "%", 0.5, 0.5, "green"),
        ]

    monkeypatch.setattr(release_gate, "compute_slos", fake_slos)
    result = await evaluate_release_gate(
        db=None, settings=_settings(), golden_pass_rate=98.0
    )
    assert result.verdict == "pass"
    assert result.failures == []


async def test_release_gate_blocks_on_correctness_regression(monkeypatch):
    """Golden pass-rate below 95% blocks deploy."""
    from app.services import release_gate, slo_service

    async def fake_slos(db, interval):
        return [
            slo_service.SloResult("full_answer", "", 4000, "ms", 2000, 3500, "green"),
            slo_service.SloResult("error_or_timeout_rate", "", 1.0, "%", 0.5, 0.5, "green"),
        ]

    monkeypatch.setattr(release_gate, "compute_slos", fake_slos)
    result = await evaluate_release_gate(
        db=None, settings=_settings(), golden_pass_rate=80.0  # below 95%
    )
    assert result.verdict == "block"
    assert any(f.gate == "correctness" for f in result.failures)


async def test_release_gate_blocks_on_latency_regression(monkeypatch):
    """full_answer p95 above the threshold blocks deploy."""
    from app.services import release_gate, slo_service

    async def fake_slos(db, interval):
        return [
            slo_service.SloResult("full_answer", "", 4000, "ms", 3000, 5500, "red"),
            slo_service.SloResult("error_or_timeout_rate", "", 1.0, "%", 0.5, 0.5, "green"),
        ]

    monkeypatch.setattr(release_gate, "compute_slos", fake_slos)
    result = await evaluate_release_gate(
        db=None, settings=_settings(), golden_pass_rate=98.0
    )
    assert result.verdict == "block"
    assert any(f.gate == "full_answer_p95" for f in result.failures)


async def test_release_gate_blocks_on_error_rate_regression(monkeypatch):
    from app.services import release_gate, slo_service

    async def fake_slos(db, interval):
        return [
            slo_service.SloResult("full_answer", "", 4000, "ms", 2000, 3500, "green"),
            slo_service.SloResult("error_or_timeout_rate", "", 1.0, "%", 3.0, 3.0, "red"),
        ]

    monkeypatch.setattr(release_gate, "compute_slos", fake_slos)
    result = await evaluate_release_gate(
        db=None, settings=_settings(), golden_pass_rate=98.0
    )
    assert result.verdict == "block"
    assert any(f.gate == "error_rate" for f in result.failures)


async def test_release_gate_skip_when_gates_disabled(monkeypatch):
    """When both gates are disabled, the verdict is always pass."""
    from app.services import release_gate

    async def fake_slos(db, interval):
        return []

    monkeypatch.setattr(release_gate, "compute_slos", fake_slos)
    s = _settings(release_gate_correctness_enabled=False, release_gate_latency_slo_enabled=False)
    result = await evaluate_release_gate(db=None, settings=s, golden_pass_rate=10.0)
    assert result.verdict == "pass"


async def test_release_gate_handles_missing_golden_pass_rate(monkeypatch):
    """When golden_pass_rate is None, the correctness gate is skipped."""
    from app.services import release_gate, slo_service

    async def fake_slos(db, interval):
        return [
            slo_service.SloResult("full_answer", "", 4000, "ms", 2000, 3500, "green"),
        ]

    monkeypatch.setattr(release_gate, "compute_slos", fake_slos)
    result = await evaluate_release_gate(db=None, settings=_settings(), golden_pass_rate=None)
    assert result.verdict == "pass"
