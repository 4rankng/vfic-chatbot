"""Coordinate-preserving, domain-neutral source blocks.

The ingestion compiler consumes these immutable blocks instead of flattened
document text, allowing every extracted value to retain reproducible evidence.
"""

from __future__ import annotations

import hashlib
import unicodedata
from dataclasses import dataclass
from typing import Literal, Sequence


CoordinateSpace = Literal["text", "sheet"]


@dataclass(frozen=True, slots=True)
class EvidenceLocator:
    coordinate_space: CoordinateSpace
    source_checksum: str
    start_offset: int | None = None
    end_offset: int | None = None
    line_start: int | None = None
    line_end: int | None = None
    normalized_offset_map: tuple[int, ...] = ()
    sheet: str | None = None
    table: str | None = None
    row_start: int | None = None
    row_end: int | None = None
    column_start: int | None = None
    column_end: int | None = None
    section_path: tuple[str, ...] = ()
    occurrence_id: str | None = None


@dataclass(frozen=True, slots=True)
class SourceBlock:
    original_text: str
    normalized_text: str
    locator: EvidenceLocator


def _checksum(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def normalize_with_offset_map(text: str) -> tuple[str, tuple[int, ...]]:
    """Normalize CRLF/NFC while mapping each normalized character to its origin."""
    normalized_parts: list[str] = []
    offsets: list[int] = []
    index = 0
    while index < len(text):
        start = index
        if text[index] == "\r":
            segment = "\n"
            index += 2 if index + 1 < len(text) and text[index + 1] == "\n" else 1
        else:
            index += 1
            while index < len(text) and unicodedata.combining(text[index]):
                index += 1
            segment = unicodedata.normalize("NFC", text[start:index])
        normalized_parts.append(segment)
        offsets.extend([start] * len(segment))
    return "".join(normalized_parts), tuple(offsets)


def source_blocks_from_text(
    source_text: str,
    *,
    source_checksum: str | None = None,
    section_path: Sequence[str] = (),
) -> list[SourceBlock]:
    """Split text into non-empty line blocks with line/character provenance."""
    checksum = source_checksum or _checksum(source_text)
    normalized, offsets = normalize_with_offset_map(source_text)
    blocks: list[SourceBlock] = []
    cursor = 0
    for line_number, line in enumerate(normalized.splitlines(keepends=True), start=1):
        content = line.rstrip("\n")
        start = cursor
        end = start + len(content)
        cursor += len(line)
        if not content.strip():
            continue
        original_start = offsets[start] if start < len(offsets) else 0
        original_end = offsets[end - 1] + 1 if end > start else original_start
        blocks.append(
            SourceBlock(
                original_text=source_text[original_start:original_end],
                normalized_text=content,
                locator=EvidenceLocator(
                    coordinate_space="text",
                    source_checksum=checksum,
                    start_offset=start,
                    end_offset=end,
                    line_start=line_number,
                    line_end=line_number,
                    normalized_offset_map=offsets[start:end],
                    section_path=tuple(section_path),
                    occurrence_id=f"line:{line_number}",
                ),
            )
        )
    return blocks


def source_blocks_from_sections(
    source_text: str,
    *,
    source_checksum: str | None = None,
    section_path: Sequence[str] = (),
) -> list[SourceBlock]:
    """Split text into blank-line-delimited logical sections with exact offsets."""
    checksum = source_checksum or _checksum(source_text)
    normalized, offsets = normalize_with_offset_map(source_text)
    blocks: list[SourceBlock] = []
    section_start: int | None = None
    section_line_start: int | None = None
    cursor = 0
    for line_number, line in enumerate(normalized.splitlines(keepends=True), start=1):
        content = line.rstrip("\n")
        line_start = cursor
        cursor += len(line)
        if content.strip():
            if section_start is None:
                section_start = line_start
                section_line_start = line_number
            continue
        if section_start is not None:
            blocks.append(
                _section_block(
                    source_text, normalized, offsets, checksum, section_start, line_start,
                    section_line_start or line_number, line_number - 1, section_path, len(blocks) + 1,
                )
            )
            section_start = None
            section_line_start = None
    if section_start is not None:
        blocks.append(
            _section_block(
                source_text, normalized, offsets, checksum, section_start, len(normalized),
                section_line_start or 1, len(normalized.splitlines()) or 1, section_path, len(blocks) + 1,
            )
        )
    return blocks


def _section_block(
    source_text: str,
    normalized: str,
    offsets: tuple[int, ...],
    checksum: str,
    start: int,
    end: int,
    line_start: int,
    line_end: int,
    section_path: Sequence[str],
    index: int,
) -> SourceBlock:
    content = normalized[start:end].rstrip("\n")
    normalized_end = start + len(content)
    original_start = offsets[start] if start < len(offsets) else 0
    original_end = offsets[normalized_end - 1] + 1 if normalized_end > start else original_start
    return SourceBlock(
        original_text=source_text[original_start:original_end],
        normalized_text=content,
        locator=EvidenceLocator(
            coordinate_space="text",
            source_checksum=checksum,
            start_offset=start,
            end_offset=normalized_end,
            line_start=line_start,
            line_end=line_end,
            normalized_offset_map=offsets[start:normalized_end],
            section_path=tuple(section_path),
            occurrence_id=f"section:{index}",
        ),
    )


def source_blocks_from_rows(
    *,
    sheet_name: str,
    headers: Sequence[str],
    rows: Sequence[Sequence[object | None]],
    source_checksum: str,
    table: str | None = None,
    section_path: Sequence[str] = (),
) -> list[SourceBlock]:
    """Build one exact-evidence block per populated spreadsheet row."""
    blocks: list[SourceBlock] = []
    for row_number, row in enumerate(rows, start=2):
        cells = ["" if value is None else str(value) for value in row]
        if not any(cell.strip() for cell in cells):
            continue
        pairs = [
            f"{header}: {cells[index]}"
            for index, header in enumerate(headers)
            if index < len(cells) and cells[index].strip()
        ]
        text = "\n".join(pairs)
        normalized, offsets = normalize_with_offset_map(text)
        blocks.append(
            SourceBlock(
                original_text=text,
                normalized_text=normalized,
                locator=EvidenceLocator(
                    coordinate_space="sheet",
                    source_checksum=source_checksum,
                    normalized_offset_map=offsets,
                    sheet=sheet_name,
                    table=table,
                    row_start=row_number,
                    row_end=row_number,
                    column_start=1,
                    column_end=min(len(headers), len(cells)),
                    section_path=tuple(section_path),
                    occurrence_id=f"{sheet_name}:row:{row_number}",
                ),
            )
        )
    return blocks
