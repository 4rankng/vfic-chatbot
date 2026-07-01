"""Eligibility scan for proactive follow-up nudges.

Queries ``conversations`` JOIN ``leads`` for BOT-mode, OPEN, not-opted-out,
interested-but-silent leads within the Zalo 48-hour window. The gap/slot-due
filter runs in Python (the ``next_due_at`` depends on ``followup_count`` which is
per-row, so a simple SQL ``now() >= last_inbound_at + GAPS[count]`` cannot be
expressed without a lateral join).
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, text

from app.core.config import (
    PROACTIVE_48H_WINDOW_SECONDS,
    PROACTIVE_FOLLOWUP_CAP,
    PROACTIVE_PER_TICK_CAP,
    PROACTIVE_RETRY_COOLDOWN_SECONDS,
)
from app.models.conversation import Conversation
from app.schemas.personas import PersonaFollowupRules, normalize_followup_rules

logger = logging.getLogger(__name__)


async def active_followup_rules(db) -> PersonaFollowupRules:
    """Return active global Agent follow-up rules, falling back to defaults.

    This mirrors the current chatbot persona resolution model: the live bot uses
    the active global Agent when no project-specific persona is selected.
    """
    raw = (
        await db.execute(
            text(
                "SELECT followup_rules FROM personas "
                "WHERE is_active AND project_id IS NULL "
                "ORDER BY updated_at DESC "
                "LIMIT 1"
            )
        )
    ).scalar_one_or_none()
    try:
        return normalize_followup_rules(raw)
    except Exception:  # noqa: BLE001
        logger.warning("invalid active Agent follow-up rules; using defaults", exc_info=True)
        return normalize_followup_rules(None)


def _stage_value(stage) -> str | None:
    return getattr(stage, "value", stage) if stage is not None else None


def _mode_value(mode) -> str | None:
    return getattr(mode, "value", mode) if mode is not None else None


def _rule_allows(
    conv: Conversation,
    *,
    lead_score: str | None,
    lead_stage: str | None,
    rules: PersonaFollowupRules,
    now: datetime,
) -> tuple[bool, str]:
    rule = rules.rule_for_score(lead_score)
    if rule is None:
        return False, "no_score_rule"
    if not rule.enabled:
        return False, "rule_disabled"
    if lead_stage not in {stage.value for stage in rule.eligible_stages}:
        return False, "stage_not_eligible"
    if conv.followup_count >= len(rule.cadence_hours):
        return False, "rule_sequence_exhausted"
    if conv.followup_count >= PROACTIVE_FOLLOWUP_CAP:
        return False, "cap_reached"
    due_at = conv.last_inbound_at + timedelta(hours=rule.cadence_hours[conv.followup_count])
    if now < due_at:
        return False, "not_due"
    return True, "due"


async def conversation_allowed_by_followup_rules(db, conv: Conversation) -> tuple[bool, str]:
    """Last-chance per-Agent rule check for an already-selected conversation."""
    if _mode_value(conv.mode) not in {"BOT", "SEMI_AUTO"}:
        return False, "mode"
    if not conv.last_inbound_at:
        return False, "no_inbound"

    row = (
        await db.execute(
            text(
                "SELECT lead_score::text AS lead_score, lead_stage::text AS lead_stage "
                "FROM leads WHERE zalo_id = :zalo_id LIMIT 1"
            ),
            {"zalo_id": conv.zalo_chat_id},
        )
    ).first()
    if row is None:
        return False, "no_lead"

    return _rule_allows(
        conv,
        lead_score=row.lead_score,
        lead_stage=row.lead_stage,
        rules=await active_followup_rules(db),
        now=datetime.now(timezone.utc),
    )


async def find_eligible_conversations(db) -> list[Conversation]:
    """Return conversation objects eligible for a proactive follow-up nudge.

    Preconditions (checked in SQL where possible):
    - ``conversation.mode in ('BOT', 'SEMI_AUTO')`` and ``status == 'OPEN'``
    - ``followup_opted_out == FALSE``
    - ``last_inbound_at`` exists and is within ``48h - margin`` (raw DB pre-filter)
    - ``followup_count < cap``
    - ``last_followup_attempt_at`` is old enough (failed-send cooldown)
    - ``bot_locked_until`` is clear
    - active Agent follow-up rule exists for the lead score
    - lead stage is included in that rule's eligible stages

    Post-filter (Python-side):
    - ``now >= last_inbound_at + active_agent_rule.cadence_hours[followup_count]``

    The SQL pre-filter intentionally omits LIMIT because the gap filter is
    per-row (depends on ``followup_count``) and ordering by newest-inbound
    first would starve actually-due older candidates.  The candidate set
    is already bounded by the 48h window + ``followup_count < cap``, so
    filtering the full set is safe.  We cap only *after* the gap filter.
    """
    margin = timedelta(seconds=PROACTIVE_48H_WINDOW_SECONDS)
    cap = PROACTIVE_FOLLOWUP_CAP
    cooldown = timedelta(seconds=PROACTIVE_RETRY_COOLDOWN_SECONDS)
    per_tick = PROACTIVE_PER_TICK_CAP
    now = datetime.now(timezone.utc)
    now_minus_margin = now - margin
    now_minus_cooldown = now - cooldown

    rules = await active_followup_rules(db)

    sql = text(
        """
        SELECT c.id, l.lead_score::text AS lead_score, l.lead_stage::text AS lead_stage
        FROM conversations c
        JOIN leads l ON l.zalo_id = c.zalo_chat_id
        WHERE c.mode IN ('BOT', 'SEMI_AUTO')
          AND c.status = 'OPEN'
          AND c.followup_opted_out = FALSE
          AND c.last_inbound_at IS NOT NULL
          AND c.last_inbound_at >= :now_minus_margin
          AND c.followup_count < :cap
          AND (c.last_followup_attempt_at IS NULL
               OR c.last_followup_attempt_at < :now_minus_cooldown)
          AND (c.bot_locked_until IS NULL OR c.bot_locked_until < now())
          AND l.lead_score IS NOT NULL
        ORDER BY c.last_inbound_at DESC
        """
    )

    result = await db.execute(
        sql,
        {
            "now_minus_margin": now_minus_margin,
            "now_minus_cooldown": now_minus_cooldown,
            "cap": cap,
        },
    )
    rows = result.fetchall()
    conv_ids = [row._mapping["id"] for row in rows]
    lead_meta = {
        str(row._mapping["id"]): (row._mapping["lead_score"], row._mapping["lead_stage"])
        for row in rows
    }
    if not conv_ids:
        return []

    stmt = select(Conversation).where(Conversation.id.in_(conv_ids))
    result = await db.execute(stmt)
    fetched = {str(conv.id): conv for conv in result.scalars().all()}
    candidates = [fetched[str(conv_id)] for conv_id in conv_ids if str(conv_id) in fetched]

    # --- Python-side rule filter: score/stage/cadence are active-Agent config ---
    eligible: list[Conversation] = []
    for conv in candidates:
        lead_score, lead_stage = lead_meta.get(str(conv.id), (None, None))
        allowed, _reason = _rule_allows(
            conv,
            lead_score=lead_score,
            lead_stage=lead_stage,
            rules=rules,
            now=now,
        )
        if allowed:
            eligible.append(conv)

    # Cap *after* the gap filter so that actually-due candidates are never
    # starved by not-yet-due rows that happen to be newer.
    pre_cap = len(eligible)
    eligible = eligible[:per_tick]

    logger.info(
        "proactive eligibility: %d candidates (SQL) → %d after gap filter → %d capped",
        len(candidates),
        pre_cap,
        len(eligible),
    )
    return eligible
