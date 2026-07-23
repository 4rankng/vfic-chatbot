"""Recruitment value types shared by domain, transport, and persistence adapters."""

from __future__ import annotations

from enum import Enum


class LeadScore(str, Enum):
    hot = "hot"
    warm = "warm"
    not_interested = "not_interested"


class LeadStage(str, Enum):
    NEW = "NEW"
    CONTACTING = "CONTACTING"
    REGISTERED = "REGISTERED"
    SKIPPED = "SKIPPED"


class FollowupStatus(str, Enum):
    PENDING = "PENDING"
    DONE = "DONE"
    SKIPPED = "SKIPPED"
    CANCELLED = "CANCELLED"


class JobStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    FULL = "FULL"
    EXPIRED = "EXPIRED"
    ARCHIVED = "ARCHIVED"

