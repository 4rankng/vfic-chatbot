"""Low-level text primitives shared by the canonical document parser and the
bus-route parser.

Both :mod:`canonical` and :mod:`bus_timetable.canonical_parser` build on these.
They live in a leaf module so the two parsers can depend on them without importing
each other — the document parser calls into the bus-route parser, so a direct
back-edge would be a circular import.
"""

from __future__ import annotations

import re
from typing import Any


def _subsections(section: str) -> list[tuple[str, str]]:
    matches = list(re.finditer(r"^###\s+(.+?)\s*$", section, flags=re.MULTILINE))
    blocks: list[tuple[str, str]] = []
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(section)
        blocks.append((match.group(1).strip(), section[start:end].strip()))
    return blocks


def _parse_scalar(value: Any) -> Any:
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


def _is_empty(value: Any) -> bool:
    return value is None or value == "" or value == []
