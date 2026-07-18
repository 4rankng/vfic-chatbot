"""Standalone knowledge-base API contracts."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.knowledge import KnowledgeBaseMode

MAX_DIRECT_CONTEXT_CHARS = 300_000


class KnowledgeBaseCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=160)
    slug: str = Field(min_length=1, max_length=96, pattern=r"^[a-z0-9][a-z0-9._-]*$")
    mode: KnowledgeBaseMode
    description: str | None = Field(default=None, max_length=4000)


class KnowledgeBaseUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=4000)


class DirectContextFileUpsert(BaseModel):
    model_config = ConfigDict(extra="forbid")

    filename: str = Field(min_length=1, max_length=255)
    text: str = Field(min_length=1, max_length=MAX_DIRECT_CONTEXT_CHARS)

    @field_validator("filename")
    @classmethod
    def require_text_filename(cls, value: str) -> str:
        filename = value.strip()
        if not filename.lower().endswith((".txt", ".md")):
            raise ValueError("direct-context knowledge accepts only .txt or .md files")
        return filename


class DirectContextFileOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    knowledge_base_id: uuid.UUID
    filename: str
    char_count: int
    line_count: int
    content_sha256: str
    updated_at: datetime


class DirectContextFileDetailOut(DirectContextFileOut):
    text: str


class DirectContextCapacityOut(BaseModel):
    provider: str
    model: str
    context_window_tokens: int
    reserved_tokens: int
    estimated_input_tokens: int
    available_input_tokens: int
    fits: bool


class KnowledgeBaseOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    slug: str
    mode: KnowledgeBaseMode
    description: str | None = None
    created_by: uuid.UUID | None = None
    created_at: datetime
    updated_at: datetime
    attached_agent_count: int = 0
    project_count: int = 0
    direct_file: DirectContextFileOut | None = None


class KnowledgeBaseListResponse(BaseModel):
    data: list[KnowledgeBaseOut]
    total: int


class KnowledgeBaseProjectFactoryOut(BaseModel):
    name: str
    aliases: list[str] = Field(default_factory=list)


class KnowledgeBaseProjectOut(BaseModel):
    """RAG catalog data needed to administer one KB's project hierarchy."""

    id: uuid.UUID
    slug: str
    name: str
    is_active: bool
    knowledge_document_count: int
    active_job_count: int
    factories: list[KnowledgeBaseProjectFactoryOut] = Field(default_factory=list)


class LegacyKnowledgeBootstrap(BaseModel):
    """Deployment-provided legacy assignment; no product names are hard-coded."""

    model_config = ConfigDict(extra="forbid")

    persona_id: uuid.UUID
    knowledge_base_name: str = Field(min_length=1, max_length=160)
    knowledge_base_slug: str = Field(
        min_length=1, max_length=96, pattern=r"^[a-z0-9][a-z0-9._-]*$"
    )
    project_ids: list[uuid.UUID] = Field(min_length=1)
    persona_name: str | None = Field(default=None, min_length=1, max_length=160)
    persona_slug: str | None = Field(
        default=None, min_length=1, max_length=96, pattern=r"^[a-z0-9][a-z0-9._-]*$"
    )
