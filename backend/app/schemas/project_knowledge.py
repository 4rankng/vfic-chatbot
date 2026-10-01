"""Project-owned Single-page and RAG category API contracts."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.project_knowledge.domain.legacy_job_references import strip_legacy_job_reference_fields
from app.project_knowledge.domain.statuses import KnowledgeCategoryRevisionStatus
from app.schemas.knowledge_categories import KnowledgeCategoryKey


class CategoryCatalogItemOut(BaseModel):
    key: KnowledgeCategoryKey
    label_vi: str
    active_revision_id: uuid.UUID | None = None
    active_revision_no: int | None = None
    active_checksum: str | None = None
    latest_revision_id: uuid.UUID | None = None
    latest_revision_no: int | None = None
    status: KnowledgeCategoryRevisionStatus | None = None
    error_message: str | None = None
    updated_at: datetime | None = None


class CategoryCatalogOut(BaseModel):
    data: list[CategoryCatalogItemOut]
    total: int


class CategoryTemplateOut(BaseModel):
    key: KnowledgeCategoryKey
    label_vi: str
    filename: str
    content: str


class CategorySourceOut(BaseModel):
    key: KnowledgeCategoryKey
    label_vi: str
    revision_id: uuid.UUID
    revision_no: int
    filename: str
    content: str
    checksum: str
    updated_at: datetime


class CategoryReplaceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    filename: str = Field(min_length=1, max_length=255)
    content: str = Field(min_length=1, max_length=500_000)

    @field_validator("filename")
    @classmethod
    def require_markdown_filename(cls, value: str) -> str:
        filename = value.strip()
        lowered = filename.lower()
        if lowered.endswith((".yaml", ".yml")):
            raise ValueError("YAML category files are not accepted; author categories in .md")
        if not lowered.endswith((".md", ".markdown", ".txt")):
            raise ValueError("RAG category uploads accept only .md, .markdown or .txt files")
        return filename


class CategoryRevisionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    category_id: uuid.UUID
    revision_no: int
    status: KnowledgeCategoryRevisionStatus
    source_filename: str
    content_sha256: str
    normalized_payload: dict
    created_at: datetime
    activated_at: datetime | None = None
    error_message: str | None = None

    @field_validator("normalized_payload", mode="after")
    @classmethod
    def omit_retired_kb_fields(cls, value: dict) -> dict:
        return strip_legacy_job_reference_fields(value)


class CategoryReplaceOut(BaseModel):
    revision: CategoryRevisionOut
    job_id: str


class CategoryClearRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confirmation: str

    @field_validator("confirmation")
    @classmethod
    def require_confirmation(cls, value: str) -> str:
        if value.strip() != "CLEAR":
            raise ValueError("confirmation must be CLEAR")
        return "CLEAR"


class CategoryCutoverRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confirmation: str

    @field_validator("confirmation")
    @classmethod
    def require_confirmation(cls, value: str) -> str:
        if value.strip() != "CUTOVER":
            raise ValueError("confirmation must be CUTOVER")
        return "CUTOVER"


class CategoryRollbackRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confirmation: str

    @field_validator("confirmation")
    @classmethod
    def require_confirmation(cls, value: str) -> str:
        if value.strip() != "ROLLBACK":
            raise ValueError("confirmation must be ROLLBACK")
        return "ROLLBACK"


class CategoryAuthorityOut(BaseModel):
    project_id: uuid.UUID
    category_authority_started: bool
    category_cutover_at: datetime | None = None
