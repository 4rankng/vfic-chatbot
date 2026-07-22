"""Project single-page external-source API contracts."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class SinglePageExternalSourceCreate(BaseModel):
    """Payload for POST /knowledge/projects/{pid}/single-page/external-sources."""

    model_config = ConfigDict(extra="forbid")

    sheet_url: str
    auto_sync_enabled: bool = False


class SinglePageExternalSourceOut(BaseModel):
    """One configured external single-page sync row."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
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
    created_at: datetime
    updated_at: datetime
