"""Deterministic, evidence-first extraction for compiler-v2 artifacts.

This layer deliberately performs no LLM calls.  It materializes every declared
occurrence separately and reports ambiguity for review rather than selecting a
last value silently.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, time
from typing import Any, Iterable

from app.services.ingestion.extraction import extract_key_value_lines
from app.services.ingestion.limits import MAX_RECORDS
from app.services.ingestion.source_blocks import EvidenceLocator, SourceBlock


@dataclass(frozen=True, slots=True)
class ExtractionIssue:
    code: str
    message: str
    record_type_key: str
    field_key: str | None = None
    occurrence_id: str | None = None


@dataclass(frozen=True, slots=True)
class ExtractedRecord:
    record_type_key: str
    occurrence_id: str
    payload: dict[str, Any]
    evidence: dict[str, EvidenceLocator]
    source_mode: str
    scope_type: str
    scope_id: str | None


def extract_compiled_records(
    artifact: dict[str, Any], blocks: Iterable[SourceBlock]
) -> tuple[list[ExtractedRecord], list[ExtractionIssue]]:
    """Extract records from a v2 artifact without losing source occurrence IDs."""
    if artifact.get("compiler_version") != "2":
        raise ValueError("generic extraction requires a compiler-v2 artifact")
    materialized_blocks = list(blocks)
    records: list[ExtractedRecord] = []
    issues: list[ExtractionIssue] = []
    for record_type in artifact.get("record_types", []):
        mode = record_type["occurrence_mode"]
        occurrences = [materialized_blocks] if mode == "single" else [[block] for block in materialized_blocks]
        for occurrence in occurrences[: record_type["max_records"]]:
            record, record_issues = _extract_occurrence(record_type, occurrence)
            issues.extend(record_issues)
            if record is not None:
                records.append(record)
                if len(records) > MAX_RECORDS:
                    raise ValueError("compiled extraction exceeds the code-owned record limit")
    return records, issues


def _extract_occurrence(
    record_type: dict[str, Any], blocks: list[SourceBlock]
) -> tuple[ExtractedRecord | None, list[ExtractionIssue]]:
    occurrence_id = blocks[0].locator.occurrence_id if blocks else None
    occurrence_id = occurrence_id or f"{record_type['key']}:empty"
    issues: list[ExtractionIssue] = []
    values = [_values_for_block(block) for block in blocks]
    payload: dict[str, Any] = {}
    evidence: dict[str, EvidenceLocator] = {}
    source_modes: set[str] = set()
    for field in record_type["fields"]:
        candidates = _field_candidates(values, field)
        unique_values = {candidate[0] for candidate in candidates}
        if len(unique_values) > 1:
            issues.append(
                ExtractionIssue(
                    code="conflicting_source_value",
                    message=f"{record_type['key']}.{field['key']} has conflicting source values",
                    record_type_key=record_type["key"],
                    field_key=field["key"],
                    occurrence_id=occurrence_id,
                )
            )
            continue
        if not candidates and field.get("constant") is not None:
            payload[field["key"]] = field["constant"]
            source_modes.add(field.get("source_mode", "sourced_fact"))
            continue
        if not candidates:
            if field["required"]:
                issues.append(
                    ExtractionIssue(
                        code="missing_required_field",
                        message=f"{record_type['key']}.{field['key']} has no source value",
                        record_type_key=record_type["key"],
                        field_key=field["key"],
                        occurrence_id=occurrence_id,
                    )
                )
            continue
        raw_value, locator = candidates[0]
        try:
            payload[field["key"]] = _coerce_value(raw_value, field)
        except ValueError as exc:
            issues.append(
                ExtractionIssue(
                    code="invalid_field_type",
                    message=f"{record_type['key']}.{field['key']}: {exc}",
                    record_type_key=record_type["key"],
                    field_key=field["key"],
                    occurrence_id=occurrence_id,
                )
            )
            continue
        evidence[field["key"]] = locator
        source_modes.add(field.get("source_mode", "sourced_fact"))
    if issues or not payload or "narrative" in source_modes:
        return None, issues
    missing_natural_key = [key for key in record_type["natural_key_fields"] if key not in payload]
    if missing_natural_key:
        issues.append(
            ExtractionIssue(
                code="missing_natural_key",
                message=f"{record_type['key']} is missing natural-key fields",
                record_type_key=record_type["key"],
                occurrence_id=occurrence_id,
            )
        )
        return None, issues
    scope_id_field = record_type.get("scope_id_field")
    return (
        ExtractedRecord(
            record_type_key=record_type["key"],
            occurrence_id=occurrence_id,
            payload=payload,
            evidence=evidence,
            source_mode="derived" if source_modes == {"derived"} else "sourced_fact",
            scope_type=record_type["scope_type"],
            scope_id=str(payload[scope_id_field]) if scope_id_field in payload else None,
        ),
        issues,
    )


def _values_for_block(block: SourceBlock) -> tuple[dict[str, str], EvidenceLocator]:
    return extract_key_value_lines(block.normalized_text), block.locator


def _field_candidates(
    values: Iterable[tuple[dict[str, str], EvidenceLocator]], field: dict[str, Any]
) -> list[tuple[str, EvidenceLocator]]:
    aliases = [field["key"], *field.get("aliases", [])]
    candidates: list[tuple[str, EvidenceLocator]] = []
    for block_values, locator in values:
        for alias in aliases:
            value = block_values.get(alias.strip().lower())
            if value:
                candidates.append((value, locator))
                break
    return candidates


def _coerce_value(value: str, field: dict[str, Any]) -> Any:
    value_type = field["type"]
    if value_type == "string":
        return value
    if value_type == "number":
        return float(value.replace(",", ""))
    if value_type == "integer":
        return int(value.replace(",", ""))
    if value_type == "boolean":
        normalized = value.strip().lower()
        if normalized in {"true", "yes", "có", "co", "1"}:
            return True
        if normalized in {"false", "no", "không", "khong", "0"}:
            return False
        raise ValueError("must be a boolean")
    if value_type == "date":
        return date.fromisoformat(value).isoformat()
    if value_type == "time":
        return time.fromisoformat(value).isoformat()
    if value_type == "enum":
        if value not in field["enum_values"]:
            raise ValueError("must match an allowed enum value")
        return value
    raise ValueError("unsupported field type")
