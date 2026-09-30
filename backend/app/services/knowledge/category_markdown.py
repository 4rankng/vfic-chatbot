"""Category Markdown v1: the admin authoring format for RAG knowledge categories.

A category document is markdown: a ``---`` front-matter naming ``schema_version`` and
``category``, then one ``## <list_field>`` section whose ``### record: <stable-id>``
blocks are the full replacement rows.  The parser decodes to the same payload dict the
YAML parser produced, and validation stays in
:func:`category_contracts.validate_category_payload`, so chunks, projections and the
agent's retrieval surface are untouched by the format swap.

Scalar encoding is type-faithful on purpose: the renderer emits numbers/booleans/null
bare and quotes every string, so ``parse(build(payload)) == payload`` holds by strict
equality.  That equality is what the data migration's round-trip check leans on.
"""

from __future__ import annotations

import re
from typing import Any, get_args, get_origin

from pydantic import BaseModel

from app.schemas.knowledge_categories import (
    CATEGORY_DOCUMENT_MODELS,
    CategoryDocument,
    KnowledgeCategoryKey,
)
from app.services.knowledge.category_contracts import (
    get_category_definition,
    validate_category_payload,
)

MAX_CATEGORY_MARKDOWN_BYTES = 500_000
MAX_CATEGORY_MARKDOWN_LINES = 20_000
MAX_CATEGORY_MARKDOWN_SCALAR_CHARS = 20_000

_FRONTMATTER_KEYS = ("schema_version", "category")

_SECTION_RE = re.compile(r"^##\s+(.+?)\s*$")
_RECORD_RE = re.compile(r"^###\s+record:\s*(\S+)\s*$")
_FIELD_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)\s*:(.*)$")
_LIST_ITEM_RE = re.compile(r"^\s*-\s+(.+)$")
_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
_INT_RE = re.compile(r"-?\d+")
_SEPARATOR_CELL_RE = re.compile(r":?-{3,}:?")
_CONTROL_CHARS_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


class CategoryMarkdownError(ValueError):
    """Raised when category source text is not one well-formed Category Markdown v1 document."""


_ESCAPES = (
    ("\\", "\\\\"),
    ('"', '\\"'),
    ("\n", "\\n"),
    ("\r", "\\r"),
    ("\t", "\\t"),
)


def _normalize(text: str) -> str:
    """Strip a leading BOM and normalize CRLF/CR line endings to LF."""
    if text.startswith("﻿"):
        text = text[1:]
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _encode_string(value: str) -> str:
    """Quote a string with the five-escape rule; other C0 control chars are stripped."""
    out = _CONTROL_CHARS_RE.sub("", value)
    for raw, escaped in _ESCAPES:
        out = out.replace(raw, escaped)
    return f'"{out}"'


def _encode_scalar(value: Any) -> str:
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, str):
        return _encode_string(value)
    return str(value)


def _unescape(body: str) -> str:
    out: list[str] = []
    escaped = False
    for ch in body:
        if escaped:
            out.append({"n": "\n", "r": "\r", "t": "\t", '"': '"', "\\": "\\"}.get(ch, ch))
            escaped = False
            continue
        if ch == "\\":
            escaped = True
            continue
        out.append(ch)
    if escaped:
        out.append("\\")
    return "".join(out)


def _decode_scalar(raw: str) -> Any:
    """Decode one scalar token, mirroring the renderer's type-faithful encoding."""
    value = raw.strip()
    if value == "null":
        return None
    if value == "true":
        return True
    if value == "false":
        return False
    if len(value) >= 2 and value.startswith('"') and value.endswith('"'):
        decoded = _unescape(value[1:-1])
    elif value.startswith("[") and value.endswith("]"):
        if value[1:-1].strip():
            raise CategoryMarkdownError(
                "inline lists are limited to []; put each entry on its own '- ' line"
            )
        return []
    elif _INT_RE.fullmatch(value):
        return int(value)
    else:
        decoded = value
    if len(decoded) > MAX_CATEGORY_MARKDOWN_SCALAR_CHARS:
        raise CategoryMarkdownError(
            f"scalar exceeds the {MAX_CATEGORY_MARKDOWN_SCALAR_CHARS:,} character limit"
        )
    return decoded


def _table_cells(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def _record_model(doc_model: type[BaseModel], list_field: str) -> type[BaseModel]:
    annotation = doc_model.model_fields[list_field].annotation
    (item,) = get_args(annotation)
    if not (isinstance(item, type) and issubclass(item, BaseModel)):
        raise CategoryMarkdownError(f"category records must be a structured model: {list_field}")
    return item


def _field_kinds(record_model: type[BaseModel]) -> dict[str, str]:
    """Classify record fields as scalar, list (dash items), or table (nested rows)."""
    kinds: dict[str, str] = {}
    for name, fld in record_model.model_fields.items():
        origin = get_origin(fld.annotation)
        if origin is list:
            (item,) = get_args(fld.annotation)
            is_model = isinstance(item, type) and issubclass(item, BaseModel)
            kinds[name] = "table" if is_model else "list"
        else:
            kinds[name] = "scalar"
    return kinds


def _table_columns(record_model: type[BaseModel], field_name: str) -> list[str]:
    item = get_args(record_model.model_fields[field_name].annotation)[0]
    return list(getattr(item, "model_fields"))


def _split_frontmatter(text: str) -> tuple[dict[str, str], str]:
    """Split the leading ``---`` front-matter and parse its ``key: value`` lines."""
    if not text.startswith("---\n"):
        raise CategoryMarkdownError("document must start with --- front-matter")
    end = text.find("\n---", 4)
    if end == -1:
        raise CategoryMarkdownError("front-matter closing --- delimiter is missing")
    meta: dict[str, str] = {}
    for no, line in enumerate(text[4:end].splitlines(), start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if ":" not in line:
            raise CategoryMarkdownError(f"front-matter line {no}: expected key: value")
        key, _, value = line.partition(":")
        meta[key.strip()] = value.strip()
    unknown = sorted(set(meta) - set(_FRONTMATTER_KEYS))
    if unknown:
        raise CategoryMarkdownError(f"unknown front-matter key(s): {', '.join(unknown)}")
    missing = [name for name in _FRONTMATTER_KEYS if name not in meta]
    if missing:
        raise CategoryMarkdownError(f"front-matter key(s) required: {', '.join(missing)}")
    return meta, text[end + 4 :].lstrip("\n")


def _parse_record(
    record_id: str,
    block: list[tuple[int, str]],
    kinds: dict[str, str],
    record_model: type[BaseModel],
) -> dict[str, Any]:
    """Decode one record block into a payload dict; the id comes from the heading."""
    record: dict[str, Any] = {"id": record_id}
    seen: set[str] = set()
    open_list: str | None = None
    open_table: str | None = None
    table_columns: list[str] = []
    header_seen = False
    for no, line in block:
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("|"):
            if open_table is None:
                raise CategoryMarkdownError(
                    f"record {record_id} line {no}: table row without an open table field"
                )
            cells = _table_cells(stripped)
            if not header_seen:
                if cells != table_columns:
                    raise CategoryMarkdownError(
                        f"record {record_id} line {no}: {open_table} table columns must be "
                        f"| {' | '.join(table_columns)} |"
                    )
                header_seen = True
                continue
            if cells and all(_SEPARATOR_CELL_RE.fullmatch(cell) for cell in cells):
                continue
            if len(cells) != len(table_columns):
                raise CategoryMarkdownError(
                    f"record {record_id} line {no}: {open_table} row has {len(cells)} of "
                    f"{len(table_columns)} columns"
                )
            record[open_table].append(
                {col: _decode_scalar(cell) for col, cell in zip(table_columns, cells) if cell}
            )
            continue
        match = _FIELD_RE.match(stripped)
        if match:
            name, raw_value = match.group(1), match.group(2).strip()
            if name not in kinds:
                raise CategoryMarkdownError(f"record {record_id} line {no}: unknown field '{name}'")
            if name in seen:
                raise CategoryMarkdownError(
                    f"record {record_id} line {no}: duplicate field '{name}'"
                )
            seen.add(name)
            open_list = None
            open_table = None
            header_seen = False
            kind = kinds[name]
            if kind == "scalar":
                if not raw_value:
                    raise CategoryMarkdownError(
                        f"record {record_id} line {no}: field '{name}' needs a value"
                    )
                record[name] = _decode_scalar(raw_value)
                continue
            if raw_value == "[]":
                record[name] = []
                continue
            if raw_value.startswith("["):
                record[name] = _decode_scalar(raw_value)
                continue
            if raw_value:
                raise CategoryMarkdownError(
                    f"record {record_id} line {no}: field '{name}' expects one entry per "
                    "'- ' line or an empty value"
                )
            record[name] = []
            if kind == "list":
                open_list = name
            else:
                open_table = name
                table_columns = _table_columns(record_model, name)
            continue
        item = _LIST_ITEM_RE.match(stripped)
        if item:
            if open_list is None:
                raise CategoryMarkdownError(
                    f"record {record_id} line {no}: list item without an open list field"
                )
            record[open_list].append(_decode_scalar(item.group(1)))
            continue
        raise CategoryMarkdownError(
            f"record {record_id} line {no}: unrecognized line: {stripped[:60]}"
        )
    return record


def _parse_section(
    body: str,
    list_field: str,
    kinds: dict[str, str],
    record_model: type[BaseModel],
) -> list[dict[str, Any]]:
    """Split the single ``## <list_field>`` section into record blocks and decode each."""
    in_section = False
    section_lines: list[tuple[int, str]] = []
    for no, line in enumerate(body.split("\n"), start=1):
        match = _SECTION_RE.match(line)
        if match:
            if in_section:
                raise CategoryMarkdownError(
                    f"line {no}: duplicate section heading; a category document has exactly "
                    f"one '## {list_field}' section"
                )
            if match.group(1) != list_field:
                raise CategoryMarkdownError(f"line {no}: section heading must be '## {list_field}'")
            in_section = True
            continue
        if in_section:
            section_lines.append((no, line))
        elif line.strip():
            raise CategoryMarkdownError(
                f"line {no}: expected the '## {list_field}' section heading first"
            )
    if not in_section:
        raise CategoryMarkdownError(f"document must contain a '## {list_field}' section")
    records: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    record_id: str | None = None
    block: list[tuple[int, str]] = []
    for no, line in section_lines:
        record_match = _RECORD_RE.match(line)
        if record_match:
            if record_id is not None:
                records.append(_parse_record(record_id, block, kinds, record_model))
            record_id = str(record_match.group(1))
            if record_id in seen_ids:
                raise CategoryMarkdownError(f"line {no}: duplicate record id '{record_id}'")
            seen_ids.add(record_id)
            block = []
            continue
        if record_id is None:
            if line.strip():
                raise CategoryMarkdownError(f"line {no}: expected a '### record: <id>' heading first")
            continue
        block.append((no, line))
    if record_id is not None:
        records.append(_parse_record(record_id, block, kinds, record_model))
    return records


def parse_category_markdown(
    key: KnowledgeCategoryKey | str,
    source_markdown: str,
    *,
    allow_empty: bool = False,
) -> CategoryDocument:
    """Parse one Category Markdown v1 document into a validated category document."""
    category_key = KnowledgeCategoryKey(key)
    if len(source_markdown.encode("utf-8")) > MAX_CATEGORY_MARKDOWN_BYTES:
        raise CategoryMarkdownError("category markdown exceeds the 500 KB limit")
    text = _normalize(source_markdown)
    if text.count("\n") + 1 > MAX_CATEGORY_MARKDOWN_LINES:
        raise CategoryMarkdownError(
            f"category markdown exceeds the {MAX_CATEGORY_MARKDOWN_LINES:,} line limit"
        )
    meta, body = _split_frontmatter(text)
    if meta["schema_version"].strip('"') != "1.0":
        raise CategoryMarkdownError('front-matter schema_version must be "1.0"')
    if meta["category"].strip('"') != category_key.value:
        raise CategoryMarkdownError(f'front-matter category must be "{category_key.value}"')
    body = _COMMENT_RE.sub("", body)
    definition = get_category_definition(category_key)
    doc_model = CATEGORY_DOCUMENT_MODELS[category_key]
    record_model = _record_model(doc_model, definition.list_field)
    kinds = _field_kinds(record_model)
    records = _parse_section(body, definition.list_field, kinds, record_model)
    payload: dict[str, Any] = {
        "schema_version": "1.0",
        "category": category_key.value,
        definition.list_field: records,
    }
    return validate_category_payload(category_key, payload, allow_empty=allow_empty)


def build_source_markdown(payload: dict[str, Any]) -> str:
    """Render a payload dict (``CategoryDocument.model_dump(mode="json")``) to markdown."""
    key = KnowledgeCategoryKey(payload["category"])
    definition = get_category_definition(key)
    record_model = _record_model(CATEGORY_DOCUMENT_MODELS[key], definition.list_field)
    kinds = _field_kinds(record_model)
    schema = payload["schema_version"]
    lines = [
        "---",
        f'schema_version: "{schema}"',
        f"category: {key.value}",
        "---",
        "",
        f"## {definition.list_field}",
        "",
    ]
    for record in payload.get(definition.list_field) or []:
        lines.append(f"### record: {record['id']}")
        for name in record_model.model_fields:
            if name == "id":
                continue
            value = record.get(name)
            kind = kinds[name]
            if kind == "scalar":
                lines.append(f"{name}: {_encode_scalar(value)}")
            elif kind == "list":
                if value:
                    lines.append(f"{name}:")
                    lines.extend(f"- {_encode_scalar(item)}" for item in value)
                else:
                    lines.append(f"{name}: []")
            elif not value:
                lines.append(f"{name}: []")
            else:
                columns = _table_columns(record_model, name)
                lines.append(f"{name}:")
                lines.append("| " + " | ".join(columns) + " |")
                lines.append("| " + " | ".join("---" for _ in columns) + " |")
                for row in value:
                    cells = " | ".join(_encode_scalar(row.get(col)) for col in columns)
                    lines.append(f"| {cells} |")
        lines.append("")
    return "\n".join(lines).rstrip("\n") + "\n"
