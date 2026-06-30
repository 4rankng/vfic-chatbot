"""Lead schemas."""
from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.models.lead import FollowupStatus, LeadScore, LeadStage


class LeadOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    zalo_id: str | None = None
    name: str | None = None
    phone: str | None = None
    birth_year: int | None = None
    age: int | None = None
    living_area: str | None = None
    address: str | None = None
    gender: str | None = None
    region: str | None = None
    desired_job: str | None = None
    years_experience: str | None = None
    latest_company: str | None = None
    expected_salary: str | None = None
    lead_score: LeadScore | None = None
    lead_stage: LeadStage
    assigned_recruiter_id: uuid.UUID | None = None
    version: int = 1
    next_action_at: datetime | None = None
    notes: str | None = None
    created_at: datetime
    updated_at: datetime


class LeadListResponse(BaseModel):
    data: list[LeadOut]
    total: int


class LeadUpdate(BaseModel):
    version: int | None = None
    name: str | None = None
    phone: str | None = None
    birth_year: int | None = None
    living_area: str | None = None
    address: str | None = None
    gender: str | None = None
    region: str | None = None
    desired_job: str | None = None
    years_experience: str | None = None
    latest_company: str | None = None
    expected_salary: str | None = None
    notes: str | None = None
    lead_score: LeadScore | None = None


class AssignRequest(BaseModel):
    recruiter_id: uuid.UUID


class StageRequest(BaseModel):
    stage: LeadStage


class FollowUpCreate(BaseModel):
    due_at: datetime
    note: str | None = None


class FollowUpOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    lead_id: int
    due_at: datetime
    note: str | None = None
    status: FollowupStatus
    created_by: uuid.UUID | None = None
    completed_at: datetime | None = None
    created_at: datetime


class LeadEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    lead_id: int
    event_type: str
    payload: dict
    actor_id: uuid.UUID | None = None
    created_at: datetime


class LeadMemoryOut(BaseModel):
    id: uuid.UUID
    content: str
    metadata: dict
    created_at: datetime
