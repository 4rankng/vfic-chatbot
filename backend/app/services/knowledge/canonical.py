"""Canonical VFIC Knowledge Markdown v1 parser.

The Markdown file is the admin authoring contract. This module converts it into
small normalized records that the ingest pipeline can trust without asking an
LLM to reinterpret business facts.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

from app.services.knowledge._canonical_helpers import _is_empty, _parse_scalar, _subsections
from app.services.knowledge.bus_timetable.canonical_parser import parse_bus_routes
from app.services.knowledge.bus_timetable.models import ParsedBusTimetable

SCHEMA_VERSION = "vfic-knowledge-v1"
CANONICAL_SCHEMA_VERSIONS = {SCHEMA_VERSION, "vfic-faq-v1"}
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
_HEADING_RE = re.compile(r"^(#{2,3})\s+(.+?)\s*$", re.MULTILINE)


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
                "company_name": document.metadata.get("company_name"),
                "locale": document.metadata["locale"],
                "audience": document.metadata["audience"],
                "content_type": document.metadata["content_type"],
                "effective_from": document.metadata["effective_from"],
                "effective_to": document.metadata.get("effective_to"),
                "tags": document.metadata.get("tags", []),
                "schema_version": document.metadata.get("schema_version", SCHEMA_VERSION),
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


def load_template() -> str:
    return TEMPLATE_PATH.read_text(encoding="utf-8")


def load_faq_template() -> str:
    return FAQ_TEMPLATE_PATH.read_text(encoding="utf-8")


def checksum_text(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


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
    if metadata.get("schema_version") not in CANONICAL_SCHEMA_VERSIONS:
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
        timetable = parse_bus_routes(metadata, sections.get("Bus Routes", ""), errors)
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


def _first_sentence(content: str) -> str:
    text = " ".join(line.strip() for line in content.splitlines() if line.strip())
    return text[:220]


def _questions_from_content(content: str) -> list[str]:
    return [value for value in [_field_value(content, "Question")] if value]


def _field_value(content: str, field: str) -> str | None:
    match = re.search(rf"^{re.escape(field)}:\s*(.+)$", content, flags=re.MULTILINE)
    return match.group(1).strip() if match else None
