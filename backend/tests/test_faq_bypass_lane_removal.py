"""Removal pins for the retired FAQ-bypass lane and the retired agent cap.

``Settings`` no longer models the agent turn cap, and an operator who leaves
``AGENT_MAX_SECONDS`` in the environment gets it silently dropped (not a
startup crash) because pydantic-settings runs with ``extra="ignore"``.
"""

from __future__ import annotations

import pytest


# ── settings ────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("env_var", ["AGENT_MAX_SECONDS", "FAQ_FAST_LANE_ENABLED"])
def test_removed_tuning_env_vars_are_dropped_without_failing_startup(monkeypatch, env_var):
    """An operator upgrading with a stale env file must not break the process,
    and must not be led to believe the knob still does something."""
    from app.core.config import Settings

    monkeypatch.setenv(env_var, "0.001")
    # A live neighbour proves extra="ignore" is in force (an unknown var is
    # tolerated, not rejected) and that Settings still binds the real fields.
    monkeypatch.setenv("SLA_SECONDS", "7.5")

    settings = Settings()

    assert settings.sla_seconds == 7.5
    assert not hasattr(settings, "agent_max_seconds")
    assert not hasattr(settings, "faq_fast_lane_enabled")
    assert not hasattr(settings, "faq_abstain_margin")
