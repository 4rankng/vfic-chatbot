"""Lead schemas."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.recruitment.domain.statuses import FollowupStatus, LeadScore, LeadStage


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
    expected_salary: str | None = None
    avatar_url: str | None = None
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


class LeadBoardQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")

    q: str | None = None
    sort: str | None = None
    order: str | None = "desc"
    per_page: int = Field(default=25, ge=1, le=100)
    section_pages: dict[str, int] = Field(default_factory=dict)


class LeadBoardSection(BaseModel):
    key: str
    title: str
    data: list[LeadOut]
    total: int
    page: int
    per_page: int
    is_priority: bool = False


class LeadBoardResponse(BaseModel):
    sections: list[LeadBoardSection]
    total: int


class LeadUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

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
    expected_salary: str | None = None
    notes: str | None = None
    lead_score: LeadScore | None = None
    lead_stage: LeadStage | None = None


class AssignRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    recruiter_id: uuid.UUID


class StageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stage: LeadStage


class FollowUpCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

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


class LeadTagOut(BaseModel):
    key: str
    label: str
    tone: Literal["good", "warn", "danger", "info"]
    system: bool = False


class LeadTagInput(BaseModel):
    key: str = Field(min_length=1, max_length=48)
    label: str | None = Field(default=None, max_length=64)
    tone: Literal["good", "warn", "danger", "info"] = "info"


class LeadTagsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    keys: list[str] = Field(default_factory=list, max_length=12)
    tags: list[LeadTagInput] = Field(default_factory=list, max_length=12)


class LeadAssistMessageOut(BaseModel):
    sender: str
    body: str
    created_at: datetime


class LeadSignalOut(BaseModel):
    key: str
    name: str
    status: str
    active: bool
    action: str | None = None


class LeadAssistOut(BaseModel):
    summary: str
    missing: list[str]
    reply: str
    next_action: str
    mode_label: str
    signals: list[LeadSignalOut]
    recent_messages: list[LeadAssistMessageOut] = Field(default_factory=list)


class LeadChatOpsActionResult(BaseModel):
    lead: LeadOut
    tags: list[LeadTagOut]
    assist: LeadAssistOut


class LeadMemoryOut(BaseModel):
    id: uuid.UUID
    content: str
    metadata: dict
    created_at: datetime
