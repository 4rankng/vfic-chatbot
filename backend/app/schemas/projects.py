"""Project ("product catalog") schemas."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class ProjectOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    slug: str
    name: str
    is_active: bool
    summary: str | None = None
    index_card: dict[str, Any] = {}
    default_persona_id: uuid.UUID | None = None
    created_at: datetime
    updated_at: datetime


class ProjectListResponse(BaseModel):
    data: list[ProjectOut]
    total: int


class ProjectCreate(BaseModel):
    slug: str
    name: str
    is_active: bool = True


class ProjectUpdate(BaseModel):
    name: str | None = None
    is_active: bool | None = None
    default_persona_id: uuid.UUID | None = None
