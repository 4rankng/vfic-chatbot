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
    PROACTIVE_FOLLOWUP_GAPS_HOURS,
    PROACTIVE_PER_TICK_CAP,
    PROACTIVE_RETRY_COOLDOWN_SECONDS,
)
from app.models.conversation import Conversation

logger = logging.getLogger(__name__)


async def find_eligible_conversations(db) -> list[Conversation]:
    """Return conversation objects eligible for a proactive follow-up nudge.

    Preconditions (checked in SQL where possible):
    - ``conversation.mode == 'BOT'`` and ``status == 'OPEN'``
    - ``followup_opted_out == FALSE``
    - ``last_inbound_at`` exists and is within ``48h - margin`` (raw DB pre-filter)
    - ``followup_count < cap``
    - ``last_followup_attempt_at`` is old enough (failed-send cooldown)
    - ``bot_locked_until`` is clear
    - lead stage is ``NEW / ENGAGED / QUALIFIED``
    - lead score is not ``not_interested``
    - lead showed interest (``desired_job`` non-empty OR ``lead_score`` in ``hot/warm``)

    Post-filter (Python-side):
    - ``now >= last_inbound_at + GAPS[followup_count]``  (slot is due)

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

    sql = text(
        """
        SELECT c.id
        FROM conversations c
        JOIN leads l ON l.zalo_id = c.zalo_chat_id
        WHERE c.mode = 'BOT'
          AND c.status = 'OPEN'
          AND c.followup_opted_out = FALSE
          AND c.last_inbound_at IS NOT NULL
          AND c.last_inbound_at >= :now_minus_margin
          AND c.followup_count < :cap
          AND (c.last_followup_attempt_at IS NULL
               OR c.last_followup_attempt_at < :now_minus_cooldown)
          AND (c.bot_locked_until IS NULL OR c.bot_locked_until < now())
          AND l.lead_stage IN ('NEW', 'ENGAGED', 'QUALIFIED')
          AND (l.lead_score IS NULL OR l.lead_score <> 'not_interested')
          AND (l.lead_score IN ('hot', 'warm')
               OR (l.desired_job IS NOT NULL AND l.desired_job <> ''))
        ORDER BY c.last_inbound_at DESC
        """
    )

    result = await db.execute(sql, {
        "now_minus_margin": now_minus_margin,
        "now_minus_cooldown": now_minus_cooldown,
        "cap": cap,
    })
    conv_ids = [row[0] for row in result.fetchall()]
    if not conv_ids:
        return []

    stmt = select(Conversation).where(Conversation.id.in_(conv_ids))
    result = await db.execute(stmt)
    candidates = list(result.scalars().all())

    # --- Python-side gap filter: only return candidates whose slot is due ---
    gaps = PROACTIVE_FOLLOWUP_GAPS_HOURS
    eligible: list[Conversation] = []
    for conv in candidates:
        idx = min(conv.followup_count, len(gaps) - 1)
        due_at = conv.last_inbound_at + timedelta(hours=gaps[idx])
        if now >= due_at:
            eligible.append(conv)

    # Cap *after* the gap filter so that actually-due candidates are never
    # starved by not-yet-due rows that happen to be newer.
    eligible = eligible[:per_tick]

    logger.info(
        "proactive eligibility: %d candidates (SQL) → %d after gap filter → %d capped",
        len(candidates),
        len(eligible) if len(eligible) <= per_tick else len(eligible),
        min(len(eligible), per_tick),
    )
    return eligible
