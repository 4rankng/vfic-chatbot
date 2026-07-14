"""Public admin contracts for the bounded ingestion-template workflow."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.models.ingestion_template import IngestionRunStatus, TemplateVersionStatus


class TemplateCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    template_key: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    name: str = Field(min_length=1, max_length=160)
    vertical: str = Field(min_length=1, max_length=64)
    definition: dict[str, Any]


class TemplateVersionUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    definition: dict[str, Any]
    revision: int = Field(ge=1)


class TemplateOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    template_key: str
    name: str
    vertical: str
    created_at: datetime


class TemplateVersionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    template_id: uuid.UUID
    version_no: int
    status: TemplateVersionStatus
    definition: dict[str, Any]
    compiled_artifact: dict[str, Any] | None = None
    checksum: str | None = None
    compiler_version: str | None = None
    revision: int
    created_at: datetime
    updated_at: datetime


class AssignmentSet(BaseModel):
    model_config = ConfigDict(extra="forbid")
    template_version_id: uuid.UUID
    revision: int = Field(ge=1)


class AssignmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    project_id: uuid.UUID
    template_version_id: uuid.UUID
    revision: int
    created_at: datetime


class IngestionRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    kb_version_id: uuid.UUID
    template_version_id: uuid.UUID
    attempt_no: int
    status: IngestionRunStatus
    manifest_sha256: str
    issues: list[dict[str, Any]] = []
    stats: dict[str, Any] = {}
    created_at: datetime


class PreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_text: str = Field(min_length=1, max_length=500_000)


class TemplatePreviewRequest(PreviewRequest):
    definition: dict[str, Any]


class PreviewOut(BaseModel):
    checksum: str
    records: list[dict[str, Any]]
    issues: list[dict[str, Any]]
