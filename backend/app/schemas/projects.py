"""Recruitment knowledge-project schemas."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.project_knowledge.domain.statuses import KnowledgeBaseMode


class FeatureReadiness(BaseModel):
    """Per-project feature readiness: how many of the active catalog features
    have enough info for the agent to advise on (vs. need more info supplied).
    The total is the active-feature count.
    """

    ready: int
    total: int


class ProjectOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    slug: str
    name: str
    aliases: list[str] = Field(default_factory=list)
    is_active: bool
    knowledge_mode: KnowledgeBaseMode | None = None
    summary: str | None = None
    index_card: dict[str, Any] = {}
    discovery_revision: int = 0
    knowledge_base_id: uuid.UUID | None = None
    knowledge_document_count: int = 0
    feature_readiness: FeatureReadiness = Field(
        default_factory=lambda: FeatureReadiness(ready=0, total=0)
    )
    created_at: datetime
    updated_at: datetime


class ProjectListResponse(BaseModel):
    data: list[ProjectOut]
    total: int


class ProjectCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    slug: str = Field(min_length=1, max_length=96, pattern=r"^[a-z0-9][a-z0-9._-]*$")
    name: str = Field(min_length=1, max_length=160)
    knowledge_mode: KnowledgeBaseMode
    aliases: list[str] = Field(default_factory=list, max_length=30)
    discovery_card: dict[str, Any] | None = None
    is_active: bool = False

    @model_validator(mode="after")
    def validate_mode_readiness(self) -> ProjectCreate:
        if self.knowledge_mode is KnowledgeBaseMode.DIRECT_CONTEXT:
            if not self.discovery_card:
                raise ValueError("Single-page Projects require a discovery card")
        elif self.discovery_card is not None:
            raise ValueError("RAG discovery cards are derived from active categories")
        if self.is_active:
            raise ValueError("A new Project can be activated after its knowledge is ready")
        return self


class ProjectUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = None
    is_active: bool | None = None
    aliases: list[str] | None = Field(default=None, max_length=30)
    discovery_card: dict[str, Any] | None = None


# --- Worker knowledge features (one row per catalog feature per project) ---


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
    """Recruiter/admin edit of a single extracted feature value."""

    model_config = ConfigDict(extra="forbid")

    value_text: str | None = None
    value_json: dict[str, Any] | None = None
    is_highlight: bool | None = None
    is_missing: bool | None = None
    needs_clarification: bool | None = None
    evidence_text: str | None = None


# --- Bus timetable (structured project route data) ---


class BusStopOut(BaseModel):
    id: uuid.UUID
    stop_order: int
    stop_name: str
    scheduled_time: str | None = None


class BusRouteOut(BaseModel):
    id: uuid.UUID
    route_name: str
    route_no: str | None = None
    route_variant: str = ""
    shift: str
    direction: str
    area: str | None = None
    mode: str | None = None
    source_page: str = ""
    notes: str | None = None
    stops: list[BusStopOut] = Field(default_factory=list)


class BusTimetableResponse(BaseModel):
    data: list[BusRouteOut]
    total: int
    page: int = 1
    per_page: int = 25


# --- Project FAQ (published canonical FAQ chunks) ---


class ProjectFaqOut(BaseModel):
    id: uuid.UUID
    question: str
    answer: str
    question_variants: list[str] = []
    required_terms: list[str] = []
    forbidden_terms: list[str] = []
    source_name: str | None = None
    source_anchor: str | None = None


class ProjectFaqResponse(BaseModel):
    data: list[ProjectFaqOut]
    total: int


class ProjectFaqCreate(BaseModel):
    question: str = Field(min_length=1, max_length=500)
    answer: str = Field(min_length=1, max_length=5000)
    # Extra phrasings of the same question (stored after the canonical one in
    # ``questions[]``) and the deterministic FAQ-bypass rule terms. All optional.
    question_variants: list[str] = Field(default_factory=list, max_length=50)
    required_terms: list[str] = Field(default_factory=list, max_length=50)
    forbidden_terms: list[str] = Field(default_factory=list, max_length=50)


class ProjectFaqUpdate(BaseModel):
    question: str | None = Field(default=None, min_length=1, max_length=500)
    answer: str | None = Field(default=None, min_length=1, max_length=5000)
    question_variants: list[str] | None = Field(default=None, max_length=50)
    required_terms: list[str] | None = Field(default=None, max_length=50)
    forbidden_terms: list[str] | None = Field(default=None, max_length=50)


# --- Per-project external API integration (admin only) ---
#
# The integration is reachable only through these routes; ``ProjectOut`` carries
# no field for it, so the sealed key never travels on the project CRUD surface.


class ProjectExternalApiKeyStatus(BaseModel):
    """Status projection of the stored key — never the value."""

    configured: bool
    preview: str | None = None


class ProjectChatbotReadiness(BaseModel):
    """Machine codes for what still blocks the chatbot's external-API call path."""

    ready: bool
    blockers: list[str] = Field(default_factory=list)


class ProjectExternalApiOut(BaseModel):
    enabled: bool
    base_url: str = ""
    auth_header: str = ""
    auth_scheme: str = ""
    guide: str = ""
    api_key: ProjectExternalApiKeyStatus
    chatbot_readiness: ProjectChatbotReadiness


class ProjectExternalApiUpdate(BaseModel):
    """Full replace of the stored config; ``api_key`` is tri-state.

    ``None``/absent keeps the sealed value, ``""`` clears it, anything else
    replaces it. Field-level rules (URL scheme, guide bounds) live in
    ``ExternalApiConfig`` so the machine codes stay in one place.
    """

    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    base_url: str = ""
    auth_header: str = "Authorization"
    auth_scheme: str = "Bearer"
    guide: str = ""
    api_key: str | None = None


class ProjectExternalApiTestIn(BaseModel):
    """Admin test-call body.

    Method/path semantics are not re-validated here: the service normalises and
    rejects them through the same code path the chatbot uses.
    """

    model_config = ConfigDict(extra="forbid")

    method: str = "GET"
    path: str = Field(min_length=1, max_length=1000)
    params: dict[str, Any] | None = None


class ProjectExternalApiTestOut(BaseModel):
    """One test call's outcome — the state the UI renders, never a transport error."""

    state: str
    status_code: int | None = None
    detail: str = ""
    text: str = ""
