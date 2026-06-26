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
    error: str | None = None


class KnowledgeDocumentListResponse(BaseModel):
    data: list[KnowledgeDocumentOut]
    total: int


class UploadRequest(BaseModel):
    """JSON text upload (kept for the Drive path / programmatic clients)."""

    file_name: str
    content: str
    drive_file_id: str | None = None
    project_id: uuid.UUID | None = None


class SearchTestRequest(BaseModel):
    query: str
    top_k: int = 10
    project_id: uuid.UUID | None = None


class SearchTestResult(BaseModel):
    content: str
    similarity: float

