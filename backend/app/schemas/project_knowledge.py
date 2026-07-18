"""Project-owned Single-page and RAG category API contracts."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.knowledge import KnowledgeCategoryRevisionStatus
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
    def require_yaml_filename(cls, value: str) -> str:
        filename = value.strip()
        if not filename.lower().endswith((".yaml", ".yml")):
            raise ValueError("RAG category uploads accept only .yaml or .yml files")
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
