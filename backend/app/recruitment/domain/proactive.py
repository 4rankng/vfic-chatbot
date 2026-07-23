"""Pure proactive follow-up rule policies."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta


@dataclass(frozen=True)
class FollowupRulePolicy:
    """One lead-score-specific proactive rule."""

    enabled: bool = True
    cadence_hours: tuple[int, ...] = ()
    eligible_stages: tuple[str, ...] = ("NEW",)


@dataclass(frozen=True)
class FollowupRulesPolicy:
    """Pure, provider-neutral follow-up policy values."""

    hot: FollowupRulePolicy = field(
        default_factory=lambda: FollowupRulePolicy(cadence_hours=(10, 22, 46))
    )
    warm: FollowupRulePolicy = field(
        default_factory=lambda: FollowupRulePolicy(cadence_hours=(22, 46))
    )
    not_interested: FollowupRulePolicy = field(
        default_factory=lambda: FollowupRulePolicy(cadence_hours=(46,))
    )

    def rule_for_score(self, score: str | None) -> FollowupRulePolicy | None:
        if score is None:
            return None
        return getattr(self, str(score), None)


def followup_rule_allows(
    *,
    followup_count: int,
    last_inbound_at: datetime,
    lead_score: str | None,
    lead_stage: str | None,
    rules: FollowupRulesPolicy,
    now: datetime,
    followup_cap: int,
) -> tuple[bool, str]:
    """Return whether the candidate is due for a proactive nudge."""
    rule = rules.rule_for_score(lead_score)
    if rule is None:
        return False, "no_score_rule"
    if not rule.enabled:
        return False, "rule_disabled"
    if lead_stage not in set(rule.eligible_stages):
        return False, "stage_not_eligible"
    if followup_count >= len(rule.cadence_hours):
        return False, "rule_sequence_exhausted"
    if followup_count >= followup_cap:
        return False, "cap_reached"
    due_at = last_inbound_at + timedelta(hours=rule.cadence_hours[followup_count])
    if now < due_at:
        return False, "not_due"
    return True, "due"


__all__ = [
    "FollowupRulePolicy",
    "FollowupRulesPolicy",
    "followup_rule_allows",
]
