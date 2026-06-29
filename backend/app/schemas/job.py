"""Job + dashboard schemas."""
from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.models.job import JobStatus


class JobBase(BaseModel):
    title: str
    company_id: uuid.UUID
    factory_name: str | None = None
    province: str | None = None
    district: str | None = None
    address: str | None = None
    salary_min: int | None = None
    salary_max: int | None = None
    shift: str | None = None
    gender_requirement: str | None = None
    age_min: int | None = None
    age_max: int | None = None
    experience_required: str | None = None
    accommodation_support: bool | None = None
    meal_support: bool | None = None
    transport_support: bool | None = None
    vacancy_count: int | None = None
    description: str | None = None
    requirements: str | None = None
    benefits: str | None = None


class JobCreate(JobBase):
    status: JobStatus = JobStatus.ACTIVE


class JobUpdate(BaseModel):
    title: str | None = None
    province: str | None = None
    salary_min: int | None = None
    salary_max: int | None = None
    vacancy_count: int | None = None
    status: JobStatus | None = None
    description: str | None = None


class JobOut(JobBase):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    status: JobStatus
    created_at: datetime
    updated_at: datetime


class JobListResponse(BaseModel):
    data: list[JobOut]
    total: int


class JobSearchResult(BaseModel):
    content: str
    similarity: float


class JobSearchRequest(BaseModel):
    query: str = ""
    top_k: int = 25


class StageBreakdownItem(BaseModel):
    """One row of the recruitment funnel: a lead stage with its scoped count and
    share of the in-scope pipeline. Order/label/color are fixed client-side from
    the canonical LEAD_STAGES list; the backend only reports value + count +
    percentage so it never downloads lead rows just to count them."""
    value: str
    count: int
    percentage: int


class KnowledgeIngestStageMetric(BaseModel):
    stage: str
    count: int


class KnowledgeIngestIssue(BaseModel):
    id: uuid.UUID
    file_name: str
    project_id: uuid.UUID | None = None
    status: str
    stage: str
    minutes_since_update: int
    error: str | None = None


class KnowledgeIngestHealth(BaseModel):
    queue_depth: int = 0
    failed_job_count: int = 0
    worker_count: int = 0
    processing_count: int = 0
    stuck_count: int = 0
    failed_document_count: int = 0
    published_document_count: int = 0
    stage_breakdown: list[KnowledgeIngestStageMetric] = []
    recent_issues: list[KnowledgeIngestIssue] = []


class DashboardMetrics(BaseModel):
    open_conversations: int
    hot_leads: int
    pending_followups: int
    bot_suppression_rate: float
    failed_zalo_sends: int = 0
    bot_errors: int = 0
    bot_run_count: int = 0
    bot_sent_count: int = 0
    bot_suppressed_count: int = 0
    bot_success_rate: float = 0.0
    avg_bot_response_seconds: float = 0.0
    # Concurrent-load monitoring (chatbot readiness)
    webhook_queue_depth: int = 0
    active_turns: int = 0
    p95_bot_response_seconds: float = 0.0
    turns_last_5min: int = 0
    # Funnel aggregates (server-side COUNT/GROUP BY, scoped like the tiles
    # above). Replaces the previous client-side useGetList(perPage=1000)
    # aggregation in useDashboardStats, which exceeded the per_page<=200 list
    # cap (422) and scaled linearly with pipeline size.
    total_leads: int = 0
    qualified_count: int = 0
    hired_count: int = 0
    hired_rate: float = 0.0
    # Conversations currently in recruiter takeover (mode=HUMAN). Preserves the
    # dashboard's existing "needs a human reply" KPI semantics verbatim.
    unread_conversation_count: int = 0
    stage_breakdown: list[StageBreakdownItem] = []
    # Admin-only operational diagnostics for knowledge ingest. Recruiters receive
    # null; backend role checks remain the source of truth.
    knowledge_ingest: KnowledgeIngestHealth | None = None
