"""Read old project knowledge without reviving retired role metadata.

These are value transformations, not stored-data migrations. Historical source,
checksums, publication checkpoints and embeddings retain their original identity.
Only structural fields are removed: occurrences inside human prose are facts
and must survive unchanged.
"""

from __future__ import annotations

import ast
import json
import re
from typing import Any


_LEGACY_FIELDS = frozenset({"job_ids", "jobs_ids", "vacancies", "employment_type"})
_REFERENCE_FIELD = re.compile(
    r"^(?P<indent>[ \t]*)(?P<bullet>[-*+]\s+)?(?:[\"']?(?P<name>job_ids|jobs_ids|vacancies|employment_type)[\"']?)\s*:\s*(?P<value>.*)$"
)
_ROLE_METADATA_FIELDS = frozenset({"vacancies", "employment_type"})
_RECORD = re.compile(r"^###\s+record:\s*\S+\s*$")
_SECTION = re.compile(r"^#{1,3}\s+")
_FENCE = re.compile(r"^\s*(`{3,}|~{3,})")
_LIST_ITEM = re.compile(r"^(?P<indent>[ \t]*)-\s+\S")
_BLOCK_SCALAR_VALUE = r"[|>](?:[-+][1-9]?|[1-9][-+]?)?(?:\s+#.*)?"
_BLOCK_SCALAR = re.compile(
    r"^(?P<indent>[ \t]*)(?P<bullet>[-*+]\s+)?"
    r"(?:[A-Za-z_][A-Za-z0-9_]*|\"(?:[^\"\\\r\n]|\\[^\r\n])*\"|'(?:[^'\r\n]|'')*')\s*:\s*"
    + _BLOCK_SCALAR_VALUE + r"\s*$"
)
_BARE_ID_ARRAY = re.compile(
    r"^\[\s*(?:[A-Za-z0-9][A-Za-z0-9._-]*(?:\s*,\s*[A-Za-z0-9][A-Za-z0-9._-]*)*)?\s*\]$"
)
_ARRAY_CONTINUATION = re.compile(
    r"^\s*(?:\]|\"(?:[^\"\\]|\\.)*\"\s*,?|\'(?:[^\'\\]|\\.)*\'\s*,?|[A-Za-z0-9][A-Za-z0-9._-]*\s*,?)\s*$"
)
_JSON_START = re.compile(r"^([ \t]*(?:[-*+]\s+)?)([\[{])")


def strip_legacy_job_reference_fields(value: Any) -> Any:
    """Copy a JSON-shaped value, dropping retired KB mapping keys only."""
    if isinstance(value, dict):
        return {
            key: strip_legacy_job_reference_fields(item)
            for key, item in value.items()
            if key not in _LEGACY_FIELDS
        }
    if isinstance(value, list):
        return [strip_legacy_job_reference_fields(item) for item in value]
    if isinstance(value, tuple):
        return tuple(strip_legacy_job_reference_fields(item) for item in value)
    return value


def _has_retained_json_value(value: Any) -> bool:
    """Recognize emptied structural containers while retaining every scalar."""
    if isinstance(value, dict):
        return any(_has_retained_json_value(item) for item in value.values())
    if isinstance(value, list):
        return any(_has_retained_json_value(item) for item in value)
    return True


def _clean_json(text: str) -> str | None:
    """Return cleaned complete JSON, or None when this is another text format."""
    stripped = text.strip()
    if not stripped.startswith(("{", "[")):
        return None
    try:
        value = json.loads(stripped)
    except (ValueError, RecursionError):
        return None
    cleaned = strip_legacy_job_reference_fields(value)
    if cleaned == value:
        return text
    if not _has_retained_json_value(cleaned):
        return ""
    left = text[: len(text) - len(text.lstrip())]
    right = text[len(text.rstrip()) :]
    rendered = json.dumps(cleaned, ensure_ascii=False, indent=2 if "\n" in stripped else None)
    return f"{left}{rendered}{right}"


def _array_end(lines: list[str], start: int, value: str) -> int | None:
    """Recognize a possibly multiline JSON/YAML inline list without eating prose."""
    if not value.startswith("["):
        return None
    parts = [value]
    for end in range(start, len(lines)):
        if end > start:
            if (
                lines[end].strip()
                and not lines[end].rstrip().endswith("]")
                and not _ARRAY_CONTINUATION.fullmatch(lines[end].rstrip("\r\n"))
            ):
                return None
            parts.append(lines[end])
        if parts[-1].rstrip().endswith("]"):
            candidate = "".join(parts)
            try:
                parsed = ast.literal_eval(candidate)
            except (ValueError, SyntaxError, RecursionError):
                parsed = None
            if isinstance(parsed, list) or _BARE_ID_ARRAY.fullmatch(candidate.strip()):
                return end + 1
            return None
    return None


def _clean_json_block(lines: list[str], start: int) -> tuple[int, str] | None:
    """Clean a JSON evidence block after a heading/bullet in a single scan."""
    marker = _JSON_START.match(lines[start])
    if marker is None:
        return None
    prefix = marker[1]
    stack: list[str] = []
    in_string = False
    escaped = False
    parts: list[str] = []
    for end in range(start, len(lines)):
        line = lines[end][len(prefix) :] if end == start else lines[end]
        if end > start and (_SECTION.match(line.strip()) or _FENCE.match(line)):
            return end, "".join(lines[start:end])
        for cursor, character in enumerate(line):
            if in_string:
                if escaped:
                    escaped = False
                elif character == "\\":
                    escaped = True
                elif character == '"':
                    in_string = False
                continue
            if character == '"':
                in_string = True
            elif character in "[{":
                stack.append(character)
            elif character in "]}":
                if not stack or stack.pop() != ("[" if character == "]" else "{"):
                    # The complete JSON decoder below owns syntax validation;
                    # this scanner only locates a balanced candidate boundary.
                    return end + 1, "".join(lines[start : end + 1])
                if not stack:
                    parts.append(line[: cursor + 1])
                    original = "".join(parts)
                    try:
                        value = json.loads(original)
                    except (ValueError, RecursionError):
                        return end + 1, "".join(lines[start : end + 1])
                    cleaned = strip_legacy_job_reference_fields(value)
                    if cleaned == value:
                        return end + 1, "".join(lines[start : end + 1])
                    if not _has_retained_json_value(cleaned):
                        return end + 1, line[cursor + 1 :]
                    rendered = json.dumps(
                        cleaned, ensure_ascii=False, indent=2 if end > start else None
                    )
                    if end > start:
                        rendered = rendered.replace("\n", "\n" + " " * len(prefix))
                    return end + 1, prefix + rendered + line[cursor + 1 :]
        parts.append(line)
    # Consume an unparseable candidate unchanged instead of repeatedly scanning
    # each nested opening bracket; malformed source must not produce quadratic
    # cleanup work or lose prose.
    return len(lines), "".join(lines[start:])


def strip_legacy_job_reference_source(text: str) -> str:
    """Hide retired fields in source Markdown, category chunks and complete JSON.

    Category record blocks permit any old field value for compatibility. Other
    Reference fields elsewhere must contain a list. Role metadata fields are
    removed wherever they appear as standalone key/value lines, including null
    and populated legacy values. Fenced examples, HTML comments, quoted prose
    within other fields and YAML block scalar prose stay intact. Original line
    endings survive when no JSON object needs re-rendering.
    """
    json_source = _clean_json(text)
    if json_source is not None:
        return json_source
    lines = text.splitlines(keepends=True)
    output: list[str] = []
    in_record = False
    fence: str | None = None
    in_comment = False
    scalar_indent: int | None = None
    skip_list_indent: int | None = None
    index = 0
    while index < len(lines):
        line = lines[index]
        stripped = line.strip()
        indent = len(line) - len(line.lstrip(" \t"))
        if scalar_indent is not None:
            if not stripped or indent > scalar_indent:
                output.append(line)
                index += 1
                continue
            scalar_indent = None
        marker = _FENCE.match(line)
        if fence is not None:
            output.append(line)
            if marker and marker[1][0] == fence[0] and len(marker[1]) >= len(fence):
                fence = None
            index += 1
            continue
        if marker:
            fence = marker[1]
            output.append(line)
            index += 1
            continue
        if in_comment or "<!--" in line:
            in_comment = "-->" not in line
            output.append(line)
            index += 1
            continue
        if _RECORD.fullmatch(stripped):
            in_record = True
            skip_list_indent = None
        elif _SECTION.match(stripped):
            in_record = False
            skip_list_indent = None
        if skip_list_indent is not None:
            item = _LIST_ITEM.match(line)
            if item and len(item["indent"]) >= skip_list_indent:
                index += 1
                continue
            if stripped:
                skip_list_indent = None
        field = _REFERENCE_FIELD.match(line.rstrip("\r\n"))
        if field:
            value = field["value"].strip()
            array_end = _array_end(lines, index, value)
            next_item = next(
                (lines[cursor] for cursor in range(index + 1, len(lines)) if lines[cursor].strip()),
                "",
            )
            item = _LIST_ITEM.match(next_item)
            has_list = (
                not value and item is not None and len(item["indent"]) >= len(field["indent"])
            )
            if (
                in_record
                or array_end is not None
                or has_list
                or field["name"] in _ROLE_METADATA_FIELDS
            ):
                # A retired YAML block scalar is one structural value. Consume
                # its indented continuation instead of leaving orphan prose.
                if re.fullmatch(_BLOCK_SCALAR_VALUE, value):
                    field_indent = len(field["indent"]) + len(field["bullet"] or "")
                    index += 1
                    while index < len(lines):
                        continuation = lines[index]
                        continuation_indent = len(continuation) - len(continuation.lstrip(" \t"))
                        if continuation.strip() and continuation_indent <= field_indent:
                            break
                        index += 1
                    continue
                skip_list_indent = (
                    len(field["indent"]) + len(field["bullet"] or "") if not value else None
                )
                index = array_end if array_end is not None else index + 1
                continue
        block_scalar = _BLOCK_SCALAR.match(line.rstrip("\r\n"))
        if block_scalar:
            scalar_indent = len(block_scalar["indent"]) + len(block_scalar["bullet"] or "")
        # Cached evidence can wrap an old JSON record in a bullet/heading.
        json_block = _clean_json_block(lines, index)
        if json_block is not None:
            index, cleaned = json_block
            output.append(cleaned)
            continue
        output.append(line)
        index += 1
    return "".join(output)
