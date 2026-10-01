"""Pure policies for project-owned category payloads."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from enum import StrEnum
from typing import TypeVar


class KnowledgeCategoryKey(StrEnum):
    JOBS = "jobs"
    COMPENSATION = "compensation"
    REQUIREMENTS = "requirements"
    WORK_SCHEDULES = "work_schedules"
    BENEFITS = "benefits"
    ACCOMMODATION = "accommodation"
    MEALS = "meals"
    TRANSPORTATION = "transportation"
    INSURANCE = "insurance"
    APPLICATION = "application"
    CONTACTS = "contacts"
    FAQ = "faq"


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


_CategoryValue = TypeVar("_CategoryValue")


def shared_project_category_value(values: list[_CategoryValue]) -> _CategoryValue | None:
    """Keep a derived role scalar unknown when project records do not agree.

    Project-level knowledge may describe distinct conditions without assigning
    them to individual roles. Publishing one conflicting record for every role
    would create a claim that the complete knowledge does not support.
    """
    if not values:
        return None
    first = values[0]
    return first if all(value == first for value in values[1:]) else None


__all__ = [
    "KnowledgeCategoryKey",
    "category_payload_checksum",
    "category_record_limit_exceeded",
    "category_replacement_is_empty",
    "shared_project_category_value",
]
