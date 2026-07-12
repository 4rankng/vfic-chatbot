"""Recruiter attention dashboard response schemas.

Strict Pydantic v2 models for ``GET /api/v1/dashboard/attention``. Authenticated
recruiters can see an anchor lead's full ``phone`` to contact the candidate;
the endpoint never exposes the ``latest_message`` body — candidate-authored
free text may carry third-party PII and is not needed to prioritize work.

``AttentionReason`` values are stable machine enums; Vietnamese labels are
frontend-owned. Reason precedence is enforced server-side (Phase 1 spec
"Reason precedence") so a candidate appears once under its highest-priority
reason.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict


class AttentionReason(str, Enum):
    """Why a candidate needs attention, in descending precedence order.

    The enum order mirrors the Phase 1 Reason Precedence list; the service
    applies dedup so each candidate surfaces under exactly one reason (the
    highest-precedence one that matches).
    """

    DELIVERY_REVIEW = "DELIVERY_REVIEW"
    HUMAN_ESCALATION = "HUMAN_ESCALATION"
    REPLY_OVERDUE = "REPLY_OVERDUE"
    FOLLOWUP_OVERDUE = "FOLLOWUP_OVERDUE"
    WAITING_REPLY = "WAITING_REPLY"
    PRIORITY_NO_ACTION = "PRIORITY_NO_ACTION"
    FOLLOWUP_TODAY = "FOLLOWUP_TODAY"
    UNREAD = "UNREAD"
    STALLED = "STALLED"


class AttentionAction(str, Enum):
    """The single primary action a recruiter takes for an attention row.

    ``OPEN_CONVERSATION`` for conversation-anchored reasons (and lead-anchored
    reasons that have a linked conversation); ``CALL`` for lead-anchored reasons
    with no conversation link (``zalo_id IS NULL``).
    """

    OPEN_CONVERSATION = "OPEN_CONVERSATION"
    CALL = "CALL"


class AttentionItemOut(BaseModel):
    """One row of the immediate or today queue.

    ``key`` is the stable dedup key: ``str(conversation_id)`` when a
    conversation exists, else ``"lead:{lead_id}"``. ``urgency_at`` is the
    timestamp the row is sorted by (oldest first within a reason). Contact
    fields (``name``, ``phone``) come from the anchor lead only.
    """

    model_config = ConfigDict(extra="forbid")

    key: str
    reason: AttentionReason
    urgency_at: datetime
    conversation_id: uuid.UUID | None = None
    lead_id: int | None = None
    name: str | None = None
    phone: str | None = None
    desired_job: str | None = None
    lead_stage: str | None = None
    lead_score: str | None = None
    last_inbound_at: datetime | None = None
    due_at: datetime | None = None
    delivery_status: str | None = None
    action: AttentionAction


class AttentionCounters(BaseModel):
    """The five exact, viewer-scoped drill-down counters.

    Each counter counts the FULL filtered set (not capped); the queue rows are
    a bounded preview. Counter keys map to reason groups:
      - ``needs_reply`` = REPLY_OVERDUE + WAITING_REPLY + HUMAN_ESCALATION
      - ``overdue``     = REPLY_OVERDUE + FOLLOWUP_OVERDUE
      - ``due_today``   = FOLLOWUP_TODAY
      - ``priority``    = PRIORITY_NO_ACTION + DELIVERY_REVIEW + STALLED
      - ``unread``      = UNREAD
    """

    model_config = ConfigDict(extra="forbid")

    needs_reply: int
    overdue: int
    due_today: int
    priority: int
    unread: int


class AttentionDashboardOut(BaseModel):
    """Top-level attention dashboard response."""

    model_config = ConfigDict(extra="forbid")

    updated_at: datetime
    counters: AttentionCounters
    immediate: list[AttentionItemOut]
    today: list[AttentionItemOut]


__all__ = [
    "AttentionAction",
    "AttentionCounters",
    "AttentionDashboardOut",
    "AttentionItemOut",
    "AttentionReason",
]
