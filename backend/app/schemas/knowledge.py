"""Knowledge schemas."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, computed_field, field_validator, model_validator

from app.project_knowledge.domain.legacy_job_references import (
    strip_legacy_job_reference_fields,
    strip_legacy_job_reference_source,
)
from app.project_knowledge.domain.statuses import KnowledgeStatus
from app.schemas.knowledge_categories import KnowledgeCategoryKey
from app.services.knowledge.file_extraction import _detect_upload_format


class ProjectTrainingWrite(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    key: KnowledgeCategoryKey
    filename: str = Field(min_length=1, max_length=255)
    content: str = Field(min_length=1, max_length=1_000_000)


class ProjectTrainingPlan(BaseModel):
    """Reviewed source-derived category proposals persisted with one upload."""

    model_config = ConfigDict(extra="forbid")
    writes: list[ProjectTrainingWrite] = Field(min_length=1, max_length=12)

    @model_validator(mode="after")
    def unique_categories(self) -> ProjectTrainingPlan:
        if len({write.key for write in self.writes}) != len(self.writes):
            raise ValueError("A project training plan cannot repeat a category")
        if sum(len(write.content) for write in self.writes) > 2_000_000:
            raise ValueError("Project training category content is too large")
        return self


class ProjectTrainingProgress(BaseModel):
    status: Literal["QUEUED", "PROCESSING", "COMPLETED", "FAILED"]
    current: KnowledgeCategoryKey | None = None
    planned: list[KnowledgeCategoryKey] = Field(default_factory=list, max_length=12)
    completed: list[KnowledgeCategoryKey] = Field(default_factory=list)
    error: str | None = None
    source_sections_total: int | None = Field(default=None, ge=0)
    source_sections_completed: int | None = Field(default=None, ge=0)
    covered_categories: list[KnowledgeCategoryKey] = Field(default_factory=list, max_length=12)
    missing_categories: list[KnowledgeCategoryKey] = Field(default_factory=list, max_length=12)
    requires_cutover: bool = Field(
        default=False,
        description="Preparation is completed but legacy knowledge still requires explicit category cutover.",
    )


class ExternalSourceCreate(BaseModel):
    """Payload for POST /knowledge/projects/{pid}/external-sources."""

    source_kind: str = "google_sheet"
    # Lowercase KnowledgeCategoryKey value; normalised + validated in the endpoint.
    category_key: str
    sheet_url: str
    sheet_gid: int = 0
    auto_sync_enabled: bool = False


class ExternalSourceSyncStateOut(BaseModel):
    """One configured external knowledge-source sync row."""

    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    project_id: uuid.UUID
    category_key: str
    source_kind: str
    sheet_url: str
    sheet_gid: int
    auto_sync_enabled: bool
    consecutive_failures: int
    last_content_hash: str | None = None
    last_synced_at: datetime | None = None
    last_status: str
    last_error: str | None = None
    last_row_count: int | None = None
    last_revision_id: uuid.UUID | None = None
    created_at: datetime
    updated_at: datetime


class KnowledgeDocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    drive_file_id: str | None = None
    file_name: str
    source: str
    version: str | None = None
    status: KnowledgeStatus
    created_at: datetime
    updated_at: datetime
    # 0003 extensions
    project_id: uuid.UUID | None = None
    project_name: str | None = None
    mime_type: str | None = None
    stage: str = "UPLOADED"
    digest_summary: str | None = None
    digest_meta: dict[str, Any] = {}
    is_canonical: bool = False
    error: str | None = None

    @field_validator("digest_summary", mode="after")
    @classmethod
    def _without_legacy_summary_fields(cls, value: str | None) -> str | None:
        return strip_legacy_job_reference_source(value) if value is not None else None

    @field_validator("digest_meta", mode="after")
    @classmethod
    def _without_legacy_metadata_fields(cls, value: dict[str, Any]) -> dict[str, Any]:
        return strip_legacy_job_reference_fields(value)

    @computed_field
    @property
    def project_training(self) -> ProjectTrainingProgress | None:
        progress = self.digest_meta.get("project_training")
        return ProjectTrainingProgress.model_validate(progress) if progress else None


class KnowledgeChunkOut(BaseModel):
    id: uuid.UUID
    chunk_index: int
    kb_version_id: uuid.UUID | None = None
    file_id: uuid.UUID | None = None
    chunk_type: str | None = None
    section_path: list[str] = []
    line_start: int | None = None
    line_end: int | None = None
    content: str
    source_quote: str | None = None
    summary: str | None = None
    questions: list[str] = []
    category: str | None = None
    entities: dict[str, Any] = {}
    confidence: str | None = None
    is_inference: bool = False
    source_anchor: str | None = None
    citation_label: str | None = None
    content_type: str | None = None
    route_id: str | None = None
    effective_from: str | None = None
    effective_to: str | None = None
    created_at: datetime

    @field_validator("content", "source_quote", "summary", mode="after")
    @classmethod
    def _without_legacy_text_fields(cls, value: str | None) -> str | None:
        return strip_legacy_job_reference_source(value) if value is not None else None

    @field_validator("questions", mode="after")
    @classmethod
    def _without_legacy_question_fields(cls, value: list[str]) -> list[str]:
        return [strip_legacy_job_reference_source(question) for question in value]

    @field_validator("entities", mode="after")
    @classmethod
    def _without_legacy_entity_fields(cls, value: dict[str, Any]) -> dict[str, Any]:
        return strip_legacy_job_reference_fields(value)


class KnowledgeChunkListResponse(BaseModel):
    data: list[KnowledgeChunkOut]
    total: int


class KnowledgeDocumentListResponse(BaseModel):
    data: list[KnowledgeDocumentOut]
    total: int


class UploadRequest(BaseModel):
    """JSON text upload (kept for the Drive path / programmatic clients)."""

    model_config = ConfigDict(extra="forbid")

    file_name: str
    content: str
    drive_file_id: str | None = None
    project_id: uuid.UUID | None = None

    @field_validator("file_name")
    @classmethod
    def _accepts_knowledge_file_formats(cls, value: str) -> str:
        """The JSON lane obeys the same format contract as the multipart lanes."""
        _detect_upload_format(value.strip(), "text/plain")
        return value

















class KnowledgeDocumentUpdate(BaseModel):
    """Admin-editable document metadata."""

    model_config = ConfigDict(extra="forbid")

    file_name: str | None = None
    project_id: uuid.UUID | None = None


class SearchTestRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str
    top_k: int = 10
    project_id: uuid.UUID | None = None


class SearchTestResult(BaseModel):
    content: str
    similarity: float

    @field_validator("content", mode="after")
    @classmethod
    def _without_legacy_text_fields(cls, value: str) -> str:
        return strip_legacy_job_reference_source(value)
