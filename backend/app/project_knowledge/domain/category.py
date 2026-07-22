"""Pure policies for category payloads and cross-category references."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping


def category_payload_checksum(payload: Mapping[str, object]) -> str:
    """Return the stable checksum used by category revision authority."""
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def category_record_limit_exceeded(record_count: int, maximum: int) -> bool:
    """Whether a parsed category exceeds its frozen record limit."""
    return record_count > maximum


def category_replacement_is_empty(record_count: int) -> bool:
    """Whether replacement content needs the explicit clear operation."""
    return record_count == 0


def unknown_job_references(
    record_job_ids: Iterable[Iterable[str]],
    known_job_ids: set[str],
) -> set[str]:
    """Collect job identifiers not owned by the current project's Jobs category."""
    unknown: set[str] = set()
    for job_ids in record_job_ids:
        unknown.update(set(job_ids) - known_job_ids)
    return unknown


__all__ = [
    "category_payload_checksum",
    "category_record_limit_exceeded",
    "category_replacement_is_empty",
    "unknown_job_references",
]
