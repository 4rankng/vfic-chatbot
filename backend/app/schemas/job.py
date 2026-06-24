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


class DashboardMetrics(BaseModel):
    open_conversations: int
    hot_leads: int
    pending_followups: int
    bot_suppression_rate: float
    failed_zalo_sends: int = 0
    bot_errors: int = 0
