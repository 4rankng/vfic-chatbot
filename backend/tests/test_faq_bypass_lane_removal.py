"""Removal pins for the retired FAQ-bypass lane and the retired agent cap.

Three things the operators and the admin surfaces could still depend on are
pinned here so the lane cannot creep back one layer at a time:

* ``Settings`` no longer models the agent turn cap, and an operator who leaves
  ``AGENT_MAX_SECONDS`` in the environment gets it silently dropped (not a
  startup crash) because pydantic-settings runs with ``extra="ignore"``.
* The performance dashboard's slow-turn payload no longer carries the retired
  stage, and a legacy row that still has the old key on disk now has that time
  counted as unmeasured dark time instead of being silently subtracted.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

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


# ── performance dashboard ───────────────────────────────────────────────────


class _FakeSlowTurnDb:
    """Returns one pre-migration bot_run row that still has the retired key."""

    def __init__(self, stage_timings: dict) -> None:
        self._row = SimpleNamespace(
            id=uuid.UUID("11111111-2222-3333-4444-555555555555"),
            conversation_id=uuid.UUID("66666666-7777-8888-9999-aaaaaaaaaaaa"),
            started_at=datetime(2026, 7, 9, 11, 42, 48, tzinfo=timezone.utc),
            outcome="SENT",
            stage_timings=stage_timings,
        )
        self.statements: list[str] = []

    async def execute(self, statement, params=None):
        self.statements.append(str(statement))
        return SimpleNamespace(all=lambda: [self._row])


@pytest.mark.asyncio
async def test_slow_turn_row_drops_the_retired_stage_and_banks_it_as_dark_time():
    from datetime import timedelta

    from app.reporting.infrastructure.performance_dashboard import _slow_turns

    db = _FakeSlowTurnDb(
        {
            "lane": "agent",
            "total_ms": 5000,
            "llm_queue_ms": 300,
            "llm_model_ms": 4200,
            "db_ms": 150,
            # Left over from before the lane was removed: 350ms of it.
            "faq_bypass_ms": 350,
        }
    )

    row = (await _slow_turns(db, timedelta(hours=1)))[0]

    assert "faq_bypass_ms" not in row
    # 5000 - (300 + 4200 + 150) = 350: the retired stage's own milliseconds are
    # no longer subtracted, so they surface as unmeasured dark time instead of
    # vanishing from the instrumentation.
    assert row["dark_time_ms"] == 350
    assert row["db_ms"] == 150
    assert row["lane"] == "agent"


@pytest.mark.asyncio
async def test_slow_turn_row_keeps_dark_time_exact_for_a_row_without_the_retired_stage():
    from datetime import timedelta

    from app.reporting.infrastructure.performance_dashboard import _slow_turns

    db = _FakeSlowTurnDb(
        {"lane": "agent", "total_ms": 5000, "llm_queue_ms": 300, "llm_model_ms": 4500, "db_ms": 150}
    )

    row = (await _slow_turns(db, timedelta(hours=1)))[0]

    assert row["dark_time_ms"] == 50
