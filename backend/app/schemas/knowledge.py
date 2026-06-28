"""Knowledge schemas."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

from app.models.knowledge import KnowledgeStatus


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
    mime_type: str | None = None
    stage: str = "UPLOADED"
    digest_summary: str | None = None
    digest_meta: dict[str, Any] = {}
    is_canonical: bool = False
    error: str | None = None


class KnowledgeChunkOut(BaseModel):
    id: uuid.UUID
    chunk_index: int
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


class KnowledgeChunkListResponse(BaseModel):
    data: list[KnowledgeChunkOut]
    total: int


class KnowledgeDocumentListResponse(BaseModel):
    data: list[KnowledgeDocumentOut]
    total: int


class UploadRequest(BaseModel):
    """JSON text upload (kept for the Drive path / programmatic clients)."""

    file_name: str
    content: str
    drive_file_id: str | None = None
    project_id: uuid.UUID | None = None


class KnowledgeDocumentUpdate(BaseModel):
    """Admin-editable document metadata."""

    file_name: str | None = None
    project_id: uuid.UUID | None = None


class SearchTestRequest(BaseModel):
    query: str
    top_k: int = 10
    project_id: uuid.UUID | None = None


class SearchTestResult(BaseModel):
    content: str
    similarity: float
