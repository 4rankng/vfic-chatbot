"""Canonical VFIC Knowledge Markdown v1 parser.

The Markdown file is the admin authoring contract. This module converts it into
small normalized records that the ingest pipeline can trust without asking an
LLM to reinterpret business facts.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import date, time
from pathlib import Path
from typing import Any

from app.services.knowledge.bus_timetable.models import (
    BusRoute,
    BusStop,
    ParsedBusTimetable,
    ServiceDay,
)
from app.services.knowledge.bus_timetable.normalize import normalize_bus_route_key

SCHEMA_VERSION = "vfic-knowledge-v1"
TEMPLATE_PATH = Path(__file__).resolve().parent / "templates" / "vfic_knowledge_v1.md"
REQUIRED_FRONTMATTER = (
    "schema_version",
    "doc_id",
    "doc_version",
    "title",
    "company_name",
    "project_slug",
    "locale",
    "audience",
    "content_type",
    "effective_from",
    "source_owner",
)
REQUIRED_SECTIONS = ("Company Overview", "Worker Features", "Rules/Policies", "FAQ", "Contacts")
FAQ_SCHEMA_VERSION = "vfic-faq-v1"
FAQ_TEMPLATE_PATH = Path(__file__).resolve().parent / "templates" / "vfic_faq_v1.md"
FAQ_REQUIRED_FRONTMATTER = (
    "schema_version",
    "doc_id",
    "doc_version",
    "title",
    "project_slug",
    "locale",
    "audience",
    "content_type",
    "effective_from",
    "source_owner",
)
FAQ_REQUIRED_SECTIONS = ("FAQ",)
ACTIVE_FEATURE_KEYS = (
    "take_home_income",
    "pay_frequency",
    "salary_transparency",
    "shift_schedule",
    "overtime_rate",
    "housing",
    "job_difficulty",
    "commute_support",
    "application_simplicity",
    "joining_bonus",
    "daily_cost_benefits",
    "contact_info",
)
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_TIME_RE = re.compile(r"^\d{2}:\d{2}$")
_HEADING_RE = re.compile(r"^(#{2,3})\s+(.+?)\s*$", re.MULTILINE)
_ROUTE_FIELD_RE = re.compile(r"^([a-zA-Z_][a-zA-Z0-9_]*):\s*(.*)$")
_SERVICE_RE = re.compile(r"^-\s*([a-z_]+):\s*(.+)$")
_SERVICE_FLAG_RE = re.compile(r"^\s*([a-z_]+)\s*=\s*([AMX])\s*$")
_VALID_DAY_GROUPS = {"mon_thu", "fri", "sat", "sun"}
_VALID_SERVICE_TYPES = {
    "outbound_admin_and_day",
    "return_night",
    "return_admin",
    "outbound_night",
    "return_day",
}


class CanonicalValidationError(ValueError):
    """Raised when a canonical document cannot be safely published."""

    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        super().__init__("; ".join(errors))


@dataclass(frozen=True)
class ParsedCitation:
    label: str
    source_anchor: str


@dataclass(frozen=True)
class ParsedKnowledgeChunk:
    content: str
    source_quote: str
    summary: str | None
    questions: list[str]
    category: str
    entities: dict[str, Any]
    citation: ParsedCitation
    section_title: str
    breadcrumb: str
    content_type: str
    tags: list[str]
    route_id: str | None = None

    def to_unit(self, document: "ParsedKnowledgeDocument") -> dict:
        metadata = {
            "document_metadata": {
                "doc_id": document.metadata["doc_id"],
                "doc_version": document.metadata["doc_version"],
                "title": document.metadata["title"],
                "company_name": document.metadata["company_name"],
                "locale": document.metadata["locale"],
                "audience": document.metadata["audience"],
                "content_type": document.metadata["content_type"],
                "effective_from": document.metadata["effective_from"],
                "effective_to": document.metadata.get("effective_to"),
                "tags": document.metadata.get("tags", []),
                "schema_version": SCHEMA_VERSION,
            },
            "chunk_metadata": {
                "section_title": self.section_title,
                "breadcrumb": self.breadcrumb,
                "content_type": self.content_type,
                "tags": self.tags,
                "route_id": self.route_id,
            },
            "citation": {
                "label": self.citation.label,
                "source_anchor": self.citation.source_anchor,
            },
        }
        return {
            "content": self.content,
            "source_quote": self.source_quote[:1000],
            "summary": self.summary,
            "questions": self.questions,
            "category": self.category,
            "entities": self.entities,
            "source_anchor": self.citation.source_anchor,
            "confidence": "high",
            "is_inference": False,
            "metadata": metadata,
            "contextual_text": build_contextual_text(document, self),
        }


@dataclass(frozen=True)
class ParsedKnowledgeDocument:
    metadata: dict[str, Any]
    chunks: list[ParsedKnowledgeChunk]
    bus_timetable: ParsedBusTimetable = field(default_factory=ParsedBusTimetable)
    checksum: str = ""

    @property
    def document_summary(self) -> str:
        return str(self.metadata.get("title") or "").strip()


@dataclass(frozen=True)
class CanonicalRepairResult:
    text: str
    repairs: list[dict[str, str]]

    @property
    def changed(self) -> bool:
        return bool(self.repairs)


def load_template() -> str:
    return TEMPLATE_PATH.read_text(encoding="utf-8")


def load_faq_template() -> str:
    return FAQ_TEMPLATE_PATH.read_text(encoding="utf-8")


def checksum_text(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def repair_canonical_markdown(text: str) -> CanonicalRepairResult:
    """Deterministically repair known non-semantic canonical Markdown mistakes.

    This pass is intentionally narrow. It fixes extractor/authoring artifacts that are
    obviously notes placed in strict fields, while leaving unknown malformed content for
    the validator to reject.
    """
    normalized = _normalize_markdown_text(text)
    blocks = list(
        re.finditer(r"^###\s+(Bus Route:\s+.+?)\s*$", normalized, flags=re.MULTILINE)
    )
    if not blocks:
        return CanonicalRepairResult(text=text, repairs=[])

    repairs: list[dict[str, str]] = []
    parts: list[str] = []
    last = 0
    for index, match in enumerate(blocks):
        start = match.start()
        end = blocks[index + 1].start() if index + 1 < len(blocks) else len(normalized)
        parts.append(normalized[last:start])
        title = match.group(1).strip()
        repaired_block, block_repairs = _repair_bus_route_block(title, normalized[start:end])
        parts.append(repaired_block)
        repairs.extend(block_repairs)
        last = end
    parts.append(normalized[last:])

    if not repairs:
        return CanonicalRepairResult(text=text, repairs=[])
    return CanonicalRepairResult(text="".join(parts), repairs=repairs)


def parse_canonical_markdown(text: str) -> ParsedKnowledgeDocument:
    # Tolerate a UTF-8 BOM and Windows CRLF line endings: an admin who edits the
    # downloaded template on Windows otherwise gets a confusing "must start with
    # YAML frontmatter" rejection, because the delimiter checks below are "\n"-
    # based. The upload-time checksum is computed over the original bytes, so this
    # local normalization does not weaken the integrity check in the pipeline.
    text = _normalize_markdown_text(text)
    errors: list[str] = []
    metadata, body = _split_frontmatter(text, errors)
    is_faq = metadata.get("schema_version") == FAQ_SCHEMA_VERSION
    if metadata.get("schema_version") not in {SCHEMA_VERSION, FAQ_SCHEMA_VERSION}:
        errors.append(f"schema_version must be {SCHEMA_VERSION!r} or {FAQ_SCHEMA_VERSION!r}")
    req_frontmatter = FAQ_REQUIRED_FRONTMATTER if is_faq else REQUIRED_FRONTMATTER
    req_sections = FAQ_REQUIRED_SECTIONS if is_faq else REQUIRED_SECTIONS
    for key in req_frontmatter:
        if _is_empty(metadata.get(key)):
            errors.append(f"frontmatter.{key} is required")
    _validate_date_field(metadata, "effective_from", errors, required=True)
    _validate_date_field(metadata, "effective_to", errors, required=False)
    if not isinstance(metadata.get("audience"), list) or not metadata.get("audience"):
        errors.append("frontmatter.audience must be a non-empty list")
    if not isinstance(metadata.get("tags"), list):
        metadata["tags"] = []

    sections = _sections(body)
    for section in req_sections:
        if section not in sections or not sections[section].strip():
            errors.append(f"section {section!r} is required and cannot be empty")

    if is_faq:
        chunks = _faq_chunks(metadata, sections.get("FAQ", ""))
        timetable = ParsedBusTimetable()
    else:
        chunks = _build_chunks(metadata, sections, errors)
        timetable = _parse_bus_routes(metadata, sections.get("Bus Routes", ""), errors)
    if errors:
        raise CanonicalValidationError(errors)
    return ParsedKnowledgeDocument(
        metadata=metadata,
        chunks=chunks,
        bus_timetable=timetable,
        checksum=checksum_text(text),
    )


def build_contextual_text(document: ParsedKnowledgeDocument, chunk: ParsedKnowledgeChunk) -> str:
    meta = document.metadata
    parts = [
        f"Document: {meta.get('title')}",
        f"Company: {meta.get('company_name')}",
        f"Section: {chunk.breadcrumb}",
        f"Content type: {chunk.content_type}",
        f"Effective from: {meta.get('effective_from')}",
    ]
    if meta.get("effective_to"):
        parts.append(f"Effective to: {meta.get('effective_to')}")
    parts.append("")
    parts.append(chunk.content)
    return "\n".join(parts).strip()


def _normalize_markdown_text(text: str) -> str:
    if text.startswith("﻿"):
        text = text[1:]
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _repair_bus_route_block(title: str, block: str) -> tuple[str, list[dict[str, str]]]:
    repairs: list[dict[str, str]] = []
    lines = block.splitlines()
    lines, service_repairs = _repair_service_days_block(title, lines)
    repairs.extend(service_repairs)
    lines, table_repairs = _repair_route_table_times(title, lines)
    repairs.extend(table_repairs)
    suffix = "\n" if block.endswith("\n") else ""
    return "\n".join(lines) + suffix, repairs


def _repair_service_days_block(
    title: str, lines: list[str]
) -> tuple[list[str], list[dict[str, str]]]:
    repairs: list[dict[str, str]] = []
    out: list[str] = []
    index = 0
    while index < len(lines):
        if lines[index].strip() != "service_days:":
            out.append(lines[index])
            index += 1
            continue

        header = lines[index]
        index += 1
        service_lines: list[str] = []
        trailing_blanks: list[str] = []
        while index < len(lines):
            stripped = lines[index].strip()
            if not stripped:
                trailing_blanks.append(lines[index])
                index += 1
                continue
            if not stripped.startswith("-"):
                break
            service_lines.append(lines[index])
            trailing_blanks = []
            index += 1

        kept: list[str] = []
        removed: list[str] = []
        for line in service_lines:
            stripped = line.strip()
            if _service_days_line_is_valid(stripped):
                kept.append(line)
            elif _service_days_line_is_repairable(stripped):
                removed.append(line)
            else:
                kept.append(line)

        if removed:
            repairs.append(
                {
                    "code": "drop_prose_service_days",
                    "section": title,
                    "detail": f"Removed {len(removed)} prose-only service_days line(s).",
                }
            )
        if kept:
            out.append(header)
            out.extend(kept)
            out.extend(trailing_blanks)
        elif not removed:
            out.append(header)
            out.extend(trailing_blanks)
    return out, repairs


def _service_days_line_is_valid(line: str) -> bool:
    match = _SERVICE_RE.match(line)
    if match is None:
        return False
    day_group, flags = match.groups()
    if day_group not in _VALID_DAY_GROUPS:
        return False
    for flag in flags.split(","):
        flag_match = _SERVICE_FLAG_RE.match(flag)
        if flag_match is None or flag_match.group(1) not in _VALID_SERVICE_TYPES:
            return False
    return True


def _service_days_line_is_repairable(line: str) -> bool:
    match = _SERVICE_RE.match(line)
    if match is None:
        return False
    day_group, flags = match.groups()
    if day_group not in _VALID_DAY_GROUPS:
        return False
    normalized = flags.strip().lower()
    return (
        normalized == "not applicable"
        or normalized.startswith("check route-specific ")
        or normalized.startswith("use ")
        or " for applicable " in normalized
        or "departure_time=" in normalized
    )


def _repair_route_table_times(
    title: str, lines: list[str]
) -> tuple[list[str], list[dict[str, str]]]:
    table_start = next((i for i, line in enumerate(lines) if line.strip().startswith("|")), None)
    if table_start is None or table_start + 2 >= len(lines):
        return lines, []
    headers = _table_cells(lines[table_start])
    if headers != ["stop_order", "stop_name", "aliases", "scheduled_time", "notes"]:
        return lines, []

    repairs: list[dict[str, str]] = []
    out = list(lines)
    for index in range(table_start + 2, len(lines)):
        if not lines[index].strip().startswith("|"):
            break
        cells = _table_cells(lines[index])
        if len(cells) != len(headers):
            continue
        raw_time = cells[3].strip()
        if not raw_time or _TIME_RE.match(raw_time):
            continue
        padded_time = _pad_hhmm(raw_time)
        if padded_time is not None:
            cells[3] = padded_time
            repairs.append(
                {
                    "code": "pad_scheduled_time",
                    "section": title,
                    "detail": f"Changed scheduled_time {raw_time!r} to {padded_time!r}.",
                }
            )
        elif re.search(r"\b\d{1,2}:\d{2}\b", raw_time):
            note = f"Scheduled time note: {raw_time}."
            cells[3] = ""
            cells[4] = " ".join(part for part in (cells[4].strip(), note) if part)
            repairs.append(
                {
                    "code": "move_non_scalar_scheduled_time_to_notes",
                    "section": title,
                    "detail": f"Moved non-scalar scheduled_time {raw_time!r} into notes.",
                }
            )
        out[index] = "| " + " | ".join(cells) + " |"
    return out, repairs


def _pad_hhmm(value: str) -> str | None:
    match = re.fullmatch(r"(\d):(\d{2})", value.strip())
    if match is None:
        return None
    return f"0{match.group(1)}:{match.group(2)}"


def _split_frontmatter(text: str, errors: list[str]) -> tuple[dict[str, Any], str]:
    if not text.startswith("---\n"):
        errors.append("document must start with YAML frontmatter delimited by ---")
        return {}, text
    end = text.find("\n---", 4)
    if end == -1:
        errors.append("frontmatter closing --- delimiter is missing")
        return {}, text
    raw = text[4:end].strip("\n")
    body = text[end + 4 :].lstrip("\r\n")
    return _parse_frontmatter(raw, errors), body


def _parse_frontmatter(raw: str, errors: list[str]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    current_key: str | None = None
    for line_no, line in enumerate(raw.splitlines(), start=1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if line.startswith("  - ") or line.startswith("- "):
            if current_key is None:
                errors.append(f"frontmatter line {line_no}: list item has no key")
                continue
            if current_key not in out:
                out[current_key] = []
            if not isinstance(out[current_key], list):
                errors.append(
                    f"frontmatter line {line_no}: list item cannot be added to scalar key {current_key!r}"
                )
                continue
            out[current_key].append(_parse_scalar(line.split("-", 1)[1].strip()))
            continue
        if ":" not in line:
            errors.append(f"frontmatter line {line_no}: expected key: value")
            continue
        key, value = line.split(":", 1)
        key = key.strip()
        current_key = key
        value = value.strip()
        out[key] = [] if value == "" else _parse_scalar(value)
    return out


def _parse_scalar(value: str) -> Any:
    value = value.strip()
    if value in {"null", "NULL", "~"}:
        return None
    if value.startswith('"') and value.endswith('"'):
        return value[1:-1]
    if value.startswith("'") and value.endswith("'"):
        return value[1:-1]
    if value.startswith("[") and value.endswith("]"):
        inner = value[1:-1].strip()
        return [] if not inner else [_parse_scalar(part.strip()) for part in inner.split(",")]
    if value.isdigit():
        return int(value)
    return value


def _sections(body: str) -> dict[str, str]:
    matches = list(_HEADING_RE.finditer(body))
    sections: dict[str, str] = {}
    top_level = [(index, match) for index, match in enumerate(matches) if match.group(1) == "##"]
    for pos, (index, match) in enumerate(top_level):
        if match.group(1) != "##":
            continue
        title = match.group(2).strip()
        start = match.end()
        next_top_index = top_level[pos + 1][0] if pos + 1 < len(top_level) else None
        end = matches[next_top_index].start() if next_top_index is not None else len(body)
        sections[title] = body[start:end].strip()
    return sections


def _validate_date_field(metadata: dict[str, Any], key: str, errors: list[str], *, required: bool) -> None:
    value = metadata.get(key)
    if value is None and not required:
        return
    if _is_empty(value):
        if required:
            errors.append(f"frontmatter.{key} is required")
        return
    if not isinstance(value, str) or not _DATE_RE.match(value):
        errors.append(f"frontmatter.{key} must use YYYY-MM-DD")
        return
    try:
        date.fromisoformat(value)
    except ValueError:
        errors.append(f"frontmatter.{key} is not a valid date")


def _build_chunks(
    metadata: dict[str, Any], sections: dict[str, str], errors: list[str]
) -> list[ParsedKnowledgeChunk]:
    chunks: list[ParsedKnowledgeChunk] = []
    for section_title, category in (("Company Overview", "job"),):
        content = sections.get(section_title, "").strip()
        if not content:
            continue
        chunks.append(_chunk(metadata, section_title, content, category))
    chunks.extend(_feature_chunks(metadata, sections.get("Worker Features", ""), errors))
    for section_title, category in (("Rules/Policies", "policy"), ("Contacts", "contact")):
        content = sections.get(section_title, "").strip()
        if content:
            chunks.append(_chunk(metadata, section_title, content, category))
    chunks.extend(_faq_chunks(metadata, sections.get("FAQ", "")))
    bus_content = sections.get("Bus Routes", "").strip()
    if bus_content:
        chunks.append(_chunk(metadata, "Bus Routes", bus_content, "schedule", route_id=None))
    return chunks


def _chunk(
    metadata: dict[str, Any],
    section_title: str,
    content: str,
    category: str,
    *,
    route_id: str | None = None,
    questions: list[str] | None = None,
    tags: list[str] | None = None,
) -> ParsedKnowledgeChunk:
    title = metadata.get("title") or metadata.get("doc_id") or "Knowledge document"
    breadcrumb = f"{title} > {section_title}"
    label = f"{title}, {section_title}"
    return ParsedKnowledgeChunk(
        content=content,
        source_quote=content,
        summary=_first_sentence(content),
        questions=questions or [f"{section_title} của {metadata.get('company_name')} là gì?"],
        category=category,
        entities={"company": metadata.get("company_name")},
        citation=ParsedCitation(label=label, source_anchor=section_title),
        section_title=section_title,
        breadcrumb=breadcrumb,
        content_type=metadata.get("content_type") or "company_knowledge",
        tags=list(dict.fromkeys([*(metadata.get("tags") or []), *(tags or [])])),
        route_id=route_id,
    )


def _feature_chunks(
    metadata: dict[str, Any], section: str, errors: list[str]
) -> list[ParsedKnowledgeChunk]:
    blocks = _subsections(section)
    seen: set[str] = set()
    chunks: list[ParsedKnowledgeChunk] = []
    for title, content in blocks:
        match = re.match(r"^Feature:\s*([a-z0-9_]+)\s*$", title, flags=re.IGNORECASE)
        if match is None:
            continue
        feature_key = match.group(1)
        if feature_key not in ACTIVE_FEATURE_KEYS:
            errors.append(f"Worker Features: unknown or inactive feature key {feature_key!r}")
            continue
        if feature_key in seen:
            errors.append(f"Worker Features: duplicate feature key {feature_key!r}")
            continue
        seen.add(feature_key)
        chunks.append(
            _chunk(
                metadata,
                f"Feature: {feature_key}",
                content,
                "feature",
                tags=[feature_key],
                questions=_questions_from_content(content)
                or [f"{feature_key} của {metadata.get('company_name')} là gì?"],
            )
        )
    return chunks


def _faq_chunks(metadata: dict[str, Any], section: str) -> list[ParsedKnowledgeChunk]:
    blocks = _subsections(section)
    chunks: list[ParsedKnowledgeChunk] = []
    for title, content in blocks:
        question = _field_value(content, "Question") or title.removeprefix("FAQ:").strip()
        answer = _field_value(content, "Answer") or content.strip()
        if not answer:
            continue
        chunks.append(
            _chunk(
                metadata,
                f"FAQ: {question}",
                answer,
                "faq",
                questions=[question] if question else None,
            )
        )
    if not chunks and section.strip():
        chunks.append(_chunk(metadata, "FAQ", section.strip(), "faq"))
    return chunks


def _parse_bus_routes(
    metadata: dict[str, Any], section: str, errors: list[str]
) -> ParsedBusTimetable:
    if not section.strip():
        return ParsedBusTimetable()
    blocks = _subsections(section)
    routes: list[BusRoute] = []
    service_days: list[ServiceDay] = []
    for title, block in blocks:
        if not title.lower().startswith("bus route:"):
            continue
        route_errors: list[str] = []
        fields, table_rows = _route_fields_and_rows(block, route_errors, title)
        mode = str(fields.get("mode") or "")
        status_only = mode == "status_only"
        required = ("route_id", "route_group", "route_name")
        if not status_only:
            required = (*required, "shift", "direction")
        for key in required:
            if _is_empty(fields.get(key)):
                route_errors.append(f"{title}: {key} is required")
        shift = str(fields.get("shift") or "")
        direction = str(fields.get("direction") or "")
        if shift and not status_only and shift not in {"day", "night", "admin"}:
            route_errors.append(f"{title}: shift must be day, night, or admin")
        if direction and not status_only and direction not in {"outbound", "return"}:
            route_errors.append(f"{title}: direction must be outbound or return")
        route_name = str(fields.get("route_name") or fields.get("route_group") or "")
        route_group = str(fields.get("route_group") or route_name)
        parsed_service_days = _parse_service_days(fields, route_group, route_errors, title)
        if status_only:
            if route_errors:
                continue
            service_days.extend(parsed_service_days)
            continue
        if not table_rows:
            route_errors.append(f"{title}: stops table is required")
        stops = [_parse_stop(row, route_errors, title) for row in table_rows]
        if route_errors:
            continue
        service_days.extend(parsed_service_days)
        route_id = str(fields.get("route_id") or normalize_bus_route_key(route_name))
        routes.append(
            BusRoute(
                route_name=route_name,
                route_no=_optional_str(fields.get("route_no")),
                route_variant=str(fields.get("route_variant") or ""),
                route_group_key=normalize_bus_route_key(route_group),
                shift=shift or "day",
                direction=direction or "outbound",
                area=_optional_str(fields.get("area")),
                mode=_optional_str(fields.get("mode")),
                source_page=str(metadata.get("doc_id") or ""),
                notes=_optional_str(fields.get("notes")),
                metadata={"route_id": route_id, "route_text": route_name, "canonical": True},
                stops=stops,
            )
        )
    return ParsedBusTimetable(routes=routes, service_days=service_days)


def _subsections(section: str) -> list[tuple[str, str]]:
    matches = list(re.finditer(r"^###\s+(.+?)\s*$", section, flags=re.MULTILINE))
    blocks: list[tuple[str, str]] = []
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(section)
        blocks.append((match.group(1).strip(), section[start:end].strip()))
    return blocks


def _route_fields_and_rows(
    block: str, errors: list[str], title: str
) -> tuple[dict[str, Any], list[dict[str, str]]]:
    fields: dict[str, Any] = {}
    lines = block.splitlines()
    table_start = next((i for i, line in enumerate(lines) if line.strip().startswith("|")), None)
    meta_lines = lines[: table_start if table_start is not None else len(lines)]
    current = None
    for raw in meta_lines:
        line = raw.strip()
        if not line:
            continue
        if line == "service_days:":
            current = "service_days"
            fields[current] = []
            continue
        if current == "service_days" and line.startswith("-"):
            fields[current].append(line)
            continue
        match = _ROUTE_FIELD_RE.match(line)
        if match:
            fields[match.group(1)] = _parse_scalar(match.group(2))
            current = None
    rows = _parse_markdown_table(lines[table_start:], errors, title) if table_start is not None else []
    return fields, rows


def _parse_markdown_table(lines: list[str], errors: list[str], title: str) -> list[dict[str, str]]:
    table = [line.strip() for line in lines if line.strip().startswith("|")]
    if len(table) < 3:
        errors.append(f"{title}: stops table is required")
        return []
    headers = _table_cells(table[0])
    required = ["stop_order", "stop_name", "aliases", "scheduled_time", "notes"]
    if headers != required:
        errors.append(f"{title}: stops table columns must be {' | '.join(required)}")
        return []
    rows = []
    for raw in table[2:]:
        cells = _table_cells(raw)
        if len(cells) != len(headers):
            errors.append(f"{title}: malformed stops table row {raw!r}")
            continue
        rows.append(dict(zip(headers, cells, strict=True)))
    return rows


def _table_cells(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def _parse_stop(row: dict[str, str], errors: list[str], title: str) -> BusStop:
    raw_order = row.get("stop_order", "")
    try:
        order = int(raw_order)
    except ValueError:
        errors.append(f"{title}: stop_order must be an integer")
        order = 0
    scheduled = None
    raw_time = (row.get("scheduled_time") or "").strip()
    if raw_time:
        if not _TIME_RE.match(raw_time):
            errors.append(f"{title}: scheduled_time must use HH:MM")
        else:
            try:
                scheduled = time.fromisoformat(raw_time)
            except ValueError:
                errors.append(f"{title}: scheduled_time is not valid")
    aliases = tuple([row.get("stop_name", "").strip()] + _split_aliases(row.get("aliases", "")))
    return BusStop(
        stop_order=order,
        stop_name=row.get("stop_name", "").strip(),
        stop_aliases=aliases,
        scheduled_time=scheduled,
        raw_stop_text=" @".join([row.get("stop_name", "").strip(), raw_time]).strip(" @"),
    )


def _parse_service_days(
    fields: dict[str, Any], route_group_name: str, errors: list[str], title: str
) -> list[ServiceDay]:
    rows: list[ServiceDay] = []
    route_group_key = normalize_bus_route_key(route_group_name)
    for raw in fields.get("service_days") or []:
        match = _SERVICE_RE.match(raw)
        if match is None:
            errors.append(f"{title}: malformed service_days line {raw!r}")
            continue
        day_group, flags = match.groups()
        if day_group not in _VALID_DAY_GROUPS:
            errors.append(f"{title}: unknown service day {day_group!r}")
            continue
        for flag in flags.split(","):
            flag_match = _SERVICE_FLAG_RE.match(flag)
            if flag_match is None:
                errors.append(f"{title}: malformed service flag {flag.strip()!r}")
                continue
            service_type, code = flag_match.groups()
            if service_type not in _VALID_SERVICE_TYPES:
                errors.append(f"{title}: unknown service type {service_type!r}")
                continue
            rows.append(
                ServiceDay(
                    route_group_key=route_group_key,
                    route_group_name=route_group_name,
                    day_group=day_group,
                    day_label=day_group,
                    service_type=service_type,
                    availability_code=code,
                    metadata={"parsed_from": "canonical_markdown"},
                )
            )
    return rows


def _split_aliases(value: str) -> list[str]:
    return [part.strip() for part in re.split(r"[,;]", value or "") if part.strip()]


def _first_sentence(content: str) -> str:
    text = " ".join(line.strip() for line in content.splitlines() if line.strip())
    return text[:220]


def _questions_from_content(content: str) -> list[str]:
    return [value for value in [_field_value(content, "Question")] if value]


def _field_value(content: str, field: str) -> str | None:
    match = re.search(rf"^{re.escape(field)}:\s*(.+)$", content, flags=re.MULTILINE)
    return match.group(1).strip() if match else None


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _is_empty(value: Any) -> bool:
    return value is None or value == "" or value == []
