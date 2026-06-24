"""Knowledge schemas."""
from __future__ import annotations

import uuid
from datetime import datetime

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


class KnowledgeDocumentListResponse(BaseModel):
    data: list[KnowledgeDocumentOut]
    total: int


class UploadRequest(BaseModel):
    file_name: str
    content: str
    drive_file_id: str | None = None


class SearchTestRequest(BaseModel):
    query: str
    top_k: int = 10


class SearchTestResult(BaseModel):
    content: str
    similarity: float
