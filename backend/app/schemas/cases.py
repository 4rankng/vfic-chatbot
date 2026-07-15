"""Generic case mutation and projection contracts."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from app.schemas.case_workflows import CaseWorkflowSummaryOut


class CaseCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    contact_id: uuid.UUID
    workflow_version_id: uuid.UUID
    workflow_checksum: str = Field(pattern=r"^[0-9a-f]{64}$")
    subject: str | None = Field(default=None, max_length=240)
    assigned_user_id: uuid.UUID | None = None
    attributes: dict[str, JsonValue] = Field(default_factory=dict, max_length=32)


class CaseUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: int = Field(ge=1)
    subject: str | None = Field(default=None, max_length=240)
    attributes: dict[str, JsonValue] = Field(default_factory=dict, max_length=32)


class CaseVersionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: int = Field(ge=1)


class CaseAssignRequest(CaseVersionRequest):
    assigned_user_id: uuid.UUID | None


class CaseTransitionRequest(CaseVersionRequest):
    target_stage_key: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{0,63}$")


class CaseTagsReplace(CaseVersionRequest):
    tag_keys: list[str] = Field(max_length=64)


class CaseNoteCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    body: str = Field(min_length=1, max_length=10_000)


class CaseFollowupCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    due_at: datetime
    note: str | None = Field(default=None, max_length=4000)
    assigned_user_id: uuid.UUID | None = None


class CaseOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    case_no: int
    contact_id: uuid.UUID
    workflow_version_id: uuid.UUID
    workflow_checksum: str
    stage_key: str
    lifecycle: Literal["OPEN", "CLOSED", "CANCELLED"]
    subject: str | None
    assigned_user_id: uuid.UUID | None
    attributes: dict[str, JsonValue]
    version: int
    closed_at: datetime | None
    tags: list[str] = Field(default_factory=list)
    workflow: CaseWorkflowSummaryOut | None = None
    created_at: datetime
    updated_at: datetime


class CaseListResponse(BaseModel):
    data: list[CaseOut]
    total: int


class CaseNoteOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    case_id: uuid.UUID
    body: str
    created_by: uuid.UUID | None
    created_at: datetime


class CaseFollowupOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    case_id: uuid.UUID
    due_at: datetime
    note: str | None
    status: Literal["PENDING", "COMPLETED", "CANCELLED"]
    assigned_user_id: uuid.UUID | None
    created_by: uuid.UUID | None
    completed_at: datetime | None
    version: int
    created_at: datetime
    updated_at: datetime
