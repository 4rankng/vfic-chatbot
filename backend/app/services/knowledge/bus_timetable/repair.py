"""Deterministic repair of known canonical-Markdown bus-timetable authoring artifacts.

Extracted from the canonical parser: the repair pass fixes extractor/authoring
mistakes that are obviously notes placed in strict fields (prose inside
``service_days``, single-digit ``HH:MM`` times, non-scalar scheduled times), while
leaving unknown malformed content for the validator to reject.

This module is intentionally self-contained — it depends only on the standard
library. The service-day grammar it shares with the canonical parser
(``SERVICE_LINE_RE``, ``SERVICE_FLAG_RE``, ``VALID_DAY_GROUPS``,
``VALID_SERVICE_TYPES``) is defined here and imported back by
:mod:`app.services.knowledge.canonical` so the two modules never import each other.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Service-day grammar shared with the canonical parser. A valid service-days line
# looks like ``- mon_thu: outbound_admin_and_day=A, return_night=M, ...``.
SERVICE_LINE_RE = re.compile(r"^-\s*([a-z_]+):\s*(.+)$")
SERVICE_FLAG_RE = re.compile(r"^\s*([a-z_]+)\s*=\s*([AMX])\s*$")
VALID_DAY_GROUPS = {"mon_thu", "fri", "sat", "sun"}
VALID_SERVICE_TYPES = {
    "outbound_admin_and_day",
    "return_night",
    "return_admin",
    "outbound_night",
    "return_day",
}

_TIME_RE = re.compile(r"^\d{2}:\d{2}$")


@dataclass(frozen=True)
class CanonicalRepairResult:
    text: str
    repairs: list[dict[str, str]]

    @property
    def changed(self) -> bool:
        return bool(self.repairs)


def repair_canonical_markdown(text: str) -> CanonicalRepairResult:
    """Deterministically repair known non-semantic canonical Markdown mistakes.

    This pass is intentionally narrow. It fixes extractor/authoring artifacts that
    are obviously notes placed in strict fields, while leaving unknown malformed
    content for the validator to reject.
    """
    normalized = _normalize_markdown_text(text)
    blocks = list(re.finditer(r"^###\s+(Bus Route:\s+.+?)\s*$", normalized, flags=re.MULTILINE))
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
    match = SERVICE_LINE_RE.match(line)
    if match is None:
        return False
    day_group, flags = match.groups()
    if day_group not in VALID_DAY_GROUPS:
        return False
    for flag in flags.split(","):
        flag_match = SERVICE_FLAG_RE.match(flag)
        if flag_match is None or flag_match.group(1) not in VALID_SERVICE_TYPES:
            return False
    return True


def _service_days_line_is_repairable(line: str) -> bool:
    match = SERVICE_LINE_RE.match(line)
    if match is None:
        return False
    day_group, flags = match.groups()
    if day_group not in VALID_DAY_GROUPS:
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


def _table_cells(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


__all__ = [
    "CanonicalRepairResult",
    "repair_canonical_markdown",
    "SERVICE_LINE_RE",
    "SERVICE_FLAG_RE",
    "VALID_DAY_GROUPS",
    "VALID_SERVICE_TYPES",
]
