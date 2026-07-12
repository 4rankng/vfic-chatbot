"""Best-effort local storage for original KB uploads.

The extracted ``raw_text`` (stored in the DB) is the source of truth, so a write
failure returns ``None`` rather than failing the upload.
"""

from __future__ import annotations

import uuid
from pathlib import Path

from app.core.config import get_settings


def persist_original_upload(file_name: str, data: bytes) -> str | None:
    """Best-effort: write the original upload to the KB volume; return its path."""
    try:
        base = Path(get_settings().kb_storage_path)
        base.mkdir(parents=True, exist_ok=True)
        safe = (
            "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in file_name)[:120]
            or "upload"
        )
        path = base / f"{uuid.uuid4().hex}_{safe}"
        path.write_bytes(data)
        return str(path)
    except Exception:  # noqa: BLE001 — storage is best-effort; raw_text is the source of truth
        return None
