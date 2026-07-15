"""Bounded, evidence-verified contract for generic LLM extraction fallback.

The caller owns the LLM invocation. This module deliberately accepts only output
that names a supplied source occurrence and quotes text from that occurrence.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from app.services.ingestion.limits import (
    MAX_LLM_CALLS_PER_RUN,
    MAX_UNRESOLVED_LLM_BLOCKS,
    bounded_batches,
)
from app.services.ingestion.source_blocks import SourceBlock


class StructuredLlmExtractionError(ValueError):
    """Raised when fallback input/output exceeds the closed extraction contract."""


def bounded_unresolved_batches(blocks: Iterable[SourceBlock]) -> list[list[SourceBlock]]:
    """Return at most ten batches of ten unresolved blocks for one ingestion run."""
    materialized = list(blocks)
    if len(materialized) > MAX_UNRESOLVED_LLM_BLOCKS:
        raise StructuredLlmExtractionError("too many unresolved source blocks")
    batches = list(bounded_batches(materialized, batch_size=10))
    if len(batches) > MAX_LLM_CALLS_PER_RUN:
        raise StructuredLlmExtractionError("LLM fallback call budget exceeded")
    return batches


def verify_sourced_fields(
    output: dict[str, Any], *, blocks: Iterable[SourceBlock]
) -> list[dict[str, Any]]:
    """Accept only fields whose quote exactly occurs in the cited source block."""
    by_occurrence = {
        block.locator.occurrence_id: block
        for block in blocks
        if block.locator.occurrence_id is not None
    }
    records = output.get("records")
    if not isinstance(records, list):
        raise StructuredLlmExtractionError("LLM output requires a records array")
    verified: list[dict[str, Any]] = []
    for record in records:
        if not isinstance(record, dict) or not isinstance(record.get("fields"), list):
            raise StructuredLlmExtractionError("each LLM record requires a fields array")
        fields: dict[str, Any] = {}
        for field in record["fields"]:
            if not isinstance(field, dict):
                raise StructuredLlmExtractionError("field must be an object")
            key, value, occurrence_id, quote = (
                field.get("key"), field.get("value"), field.get("occurrence_id"), field.get("quote")
            )
            block = by_occurrence.get(occurrence_id)
            if not isinstance(key, str) or block is None or not isinstance(quote, str):
                raise StructuredLlmExtractionError("field has invalid evidence reference")
            if not quote or quote not in block.normalized_text:
                raise StructuredLlmExtractionError("field quote does not match cited source block")
            fields[key] = value
        verified.append({"record_type_key": record.get("record_type_key"), "fields": fields})
    return verified
