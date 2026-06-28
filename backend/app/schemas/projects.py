"""Project ("product catalog") schemas."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class FeatureReadiness(BaseModel):
    """Per-project feature readiness: how many of the active catalog features
    have enough info for the agent to advise on (vs. need more info supplied).
    The total is the active-feature count (11 for manual-labour scope; migration 0009).
    """

    ready: int
    total: int


class ProjectOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    slug: str
    name: str
    is_active: bool
    summary: str | None = None
    index_card: dict[str, Any] = {}
    default_persona_id: uuid.UUID | None = None
    feature_readiness: FeatureReadiness = Field(
        default_factory=lambda: FeatureReadiness(ready=0, total=11)
    )
    created_at: datetime
    updated_at: datetime


class ProjectListResponse(BaseModel):
    data: list[ProjectOut]
    total: int


class ProjectCreate(BaseModel):
    slug: str
    name: str
    is_active: bool = True


class ProjectUpdate(BaseModel):
    name: str | None = None
    is_active: bool | None = None
    default_persona_id: uuid.UUID | None = None


# --- Worker product features (one row per catalog feature per project) ---


class FeatureOut(BaseModel):
    """A job_feature_values row joined with its catalog metadata (worker-facing)."""

    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    project_id: uuid.UUID
    feature_id: uuid.UUID
    feature_key: str
    name_vi: str
    category: str
    worker_question_vi: str | None = None
    value_text: str
    value_json: dict[str, Any] = {}
    strength_score: float
    display_priority: int
    is_highlight: bool
    is_missing: bool
    needs_clarification: bool
    evidence_text: str | None = None
    source_document_id: uuid.UUID | None = None
    updated_at: datetime


class FeatureListResponse(BaseModel):
    data: list[FeatureOut]
    total: int


class FeatureUpdate(BaseModel):
    """Admin edit of a single extracted feature value."""

    value_text: str | None = None
    value_json: dict[str, Any] | None = None
    is_highlight: bool | None = None
    is_missing: bool | None = None
    needs_clarification: bool | None = None
    evidence_text: str | None = None
