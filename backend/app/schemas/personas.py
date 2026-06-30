"""Persona schemas."""
from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


def _slugify(name: str) -> str:
    out = []
    for ch in name.strip().lower():
        out.append(ch if ch.isalnum() or ch in "-_" else "-")
    slug = "".join(out).strip("-")
    # collapse repeated separators
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug or "persona"


class PersonaOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    project_id: uuid.UUID | None = None
    name: str
    slug: str
    body_md: str
    is_active: bool
    notes: str | None = None
    created_by: uuid.UUID | None = None
    created_at: datetime
    updated_at: datetime
    assigned_projects: list[ProjectMini] = []


class PersonaListResponse(BaseModel):
    data: list[PersonaOut]
    total: int


class PersonaCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    body_md: str = Field(min_length=1)
    slug: str | None = None  # derived from name if absent
    notes: str | None = None
    is_active: bool = False


class PersonaUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = None
    body_md: str | None = None
    notes: str | None = None


class ProjectMini(BaseModel):
    """Minimal project representation used in persona assignment lists."""

    id: uuid.UUID
    name: str
    slug: str
