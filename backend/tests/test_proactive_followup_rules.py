"""Unit tests for active-Agent proactive follow-up rule semantics."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from app.schemas.personas import default_followup_rules
from app.services.proactive.repository import _rule_allows


def _conv(*, count: int, last_inbound_at: datetime):
    return SimpleNamespace(followup_count=count, last_inbound_at=last_inbound_at)


def test_hot_rule_first_slot_due_after_10_hours():
    now = datetime.now(timezone.utc)
    allowed, reason = _rule_allows(
        _conv(count=0, last_inbound_at=now - timedelta(hours=10)),
        lead_score="hot",
        lead_stage="NEW",
        rules=default_followup_rules(),
        now=now,
    )

    assert allowed is True
    assert reason == "due"


def test_warm_rule_second_slot_due_after_46_hours():
    now = datetime.now(timezone.utc)
    allowed, reason = _rule_allows(
        _conv(count=1, last_inbound_at=now - timedelta(hours=46)),
        lead_score="warm",
        lead_stage="NEW",
        rules=default_followup_rules(),
        now=now,
    )

    assert allowed is True
    assert reason == "due"


def test_cold_rule_uses_not_interested_score_and_46_hour_slot():
    now = datetime.now(timezone.utc)
    allowed, reason = _rule_allows(
        _conv(count=0, last_inbound_at=now - timedelta(hours=46)),
        lead_score="not_interested",
        lead_stage="NEW",
        rules=default_followup_rules(),
        now=now,
    )

    assert allowed is True
    assert reason == "due"


def test_rule_rejects_unconfigured_stage_and_exhausted_sequence():
    now = datetime.now(timezone.utc)
    rules = default_followup_rules()

    allowed, reason = _rule_allows(
        _conv(count=0, last_inbound_at=now - timedelta(hours=46)),
        lead_score="hot",
        lead_stage="CONTACTING",
        rules=rules,
        now=now,
    )
    assert allowed is False
    assert reason == "stage_not_eligible"

    allowed, reason = _rule_allows(
        _conv(count=1, last_inbound_at=now - timedelta(hours=46)),
        lead_score="not_interested",
        lead_stage="NEW",
        rules=rules,
        now=now,
    )
    assert allowed is False
    assert reason == "rule_sequence_exhausted"
