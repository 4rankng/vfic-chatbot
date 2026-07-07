"""Deterministic helpers for text-only KB ingestion."""

from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass

from app.core.text import normalize_vietnamese_text


@dataclass(frozen=True)
class TextStats:
    normalized_text: str
    content_sha256: str
    char_count: int
    line_count: int


def normalize_kb_text(raw: str) -> str:
    text = raw.replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace("\ufeff", "")
    text = unicodedata.normalize("NFC", text)
    text = "".join(ch for ch in text if ch == "\n" or ch == "\t" or ch >= " ")
    text = re.sub(r"\n{4,}", "\n\n\n", text)
    return text.strip()


def kb_text_stats(raw: str) -> TextStats:
    normalized = normalize_kb_text(raw)
    return TextStats(
        normalized_text=normalized,
        content_sha256=hash_text(normalized),
        char_count=len(normalized),
        line_count=0 if not normalized else normalized.count("\n") + 1,
    )


def hash_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def make_content_plain(*parts: str | None) -> str:
    return normalize_vietnamese_text(" ".join(part or "" for part in parts))


def estimate_token_count(value: str) -> int:
    # Good enough for Vietnamese MVP chunk telemetry without binding to a tokenizer.
    return len(re.findall(r"\S+", value or ""))


def line_range_for_quote(source_text: str, quote: str | None) -> tuple[int | None, int | None]:
    needle = normalize_kb_text(quote or "")
    if not source_text or not needle:
        return (None, None)
    haystack = normalize_kb_text(source_text)
    index = haystack.find(needle)
    if index < 0:
        compact_needle = _compact(needle)
        if not compact_needle:
            return (None, None)
        compact_haystack = _compact(haystack)
        compact_index = compact_haystack.find(compact_needle)
        if compact_index < 0:
            return (None, None)
        index = _original_index_for_compact_offset(haystack, compact_index)
    start = haystack.count("\n", 0, index) + 1
    end = start + haystack[index : index + len(needle)].count("\n")
    return (start, end)


def section_path_from_metadata(metadata: dict) -> list[str]:
    chunk_meta = metadata.get("chunk_metadata") or {}
    breadcrumb = str(chunk_meta.get("breadcrumb") or "").strip()
    if breadcrumb:
        return [part.strip() for part in breadcrumb.split(">") if part.strip()]
    section = str(chunk_meta.get("section_title") or metadata.get("source_anchor") or "").strip()
    return [section] if section else []


def chunk_type_from_metadata(metadata: dict, category: str | None) -> str:
    chunk_meta = metadata.get("chunk_metadata") or {}
    content_type = str(chunk_meta.get("content_type") or "").strip()
    if category == "faq":
        return "faq"
    if category == "schedule" and str(chunk_meta.get("route_id") or "").strip():
        return "markdown_table"
    return content_type or category or "text"


def _compact(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _original_index_for_compact_offset(value: str, compact_offset: int) -> int:
    compact_seen = 0
    in_space = False
    for index, char in enumerate(value):
        if char.isspace():
            if not in_space:
                if compact_seen == compact_offset:
                    return index
                compact_seen += 1
                in_space = True
            continue
        if compact_seen == compact_offset:
            return index
        compact_seen += 1
        in_space = False
    return len(value)
