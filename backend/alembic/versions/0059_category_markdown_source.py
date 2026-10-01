"""Rename category revision source to source_markdown; convert rows to Category Markdown v1.

The markdown cutover made Category Markdown v1 the only authoring format for
project knowledge categories. This migration renames
``knowledge_category_revisions.source_yaml`` to ``source_markdown`` and converts
every stored revision and its activated document from YAML to markdown.

Per-row conversion is verified by round-trip: the payload truth
(``normalized_payload`` JSONB) is rendered to markdown by the frozen renderer
below, re-parsed by the frozen parser, and must equal the payload by strict
dict equality. Any mismatch aborts the migration before any change is visible
(Postgres DDL and DML roll back together). A legacy-source sanity check (the
last sanctioned PyYAML use in this codebase) requires the old ``source_yaml``
text to parse as a YAML or JSON mapping whose top-level ``category`` matches
the row — stored source/payload drift fails loudly instead of converting.

Downgrade restores the schema and the document provenance literals only; the
stored text is NOT reconstructed to YAML. Content rollback means restoring the
pre-migration backup taken by the deployment workflow.

Stored payloads may omit declared fields outright (the serializer skipped
them), which carries the same information as the empty form: the pydantic
models default those fields to None/[] and the grammar renders the empty
form. The round-trip check therefore compares against a payload whose
declared fields have been materialized, so absent-vs-empty key presence
cannot mask real content loss.

One content shape fails the round-trip loudly by design: a nested table cell
(shift, stop, allowance, bonus names) containing the pipe character cannot
survive a markdown table, so such a row needs a data fix before migrating.

Revision ID: 0059_category_markdown_source
Revises: 0058_tingting_hotline_setting
"""

from alembic import op
import sqlalchemy as sa
import yaml  # noqa: F401  — migration-only legacy-source sanity check

revision = "0059_category_markdown_source"
down_revision = "0058_tingting_hotline_setting"
branch_labels = None
depends_on = None

# Frozen copy of the per-category record grammar (field name, kind, table
# columns) matching app/schemas/knowledge_categories.py at the markdown
# cutover. The living original is app/services/knowledge/category_markdown.py,
# which derives it from the pydantic models; this copy exists because version
# migrations must not import application code.
_FIELD_TABLES = {
    "jobs": ("jobs", (
        ("id", "scalar", None),
        ("title", "scalar", None),
        ("aliases", "list", None),
        ("location", "scalar", None),
        ("vacancies", "scalar", None),
        ("employment_type", "scalar", None),
        ("summary", "scalar", None),
        ("keywords", "list", None),
    )),
    "compensation": ("compensation", (
        ("id", "scalar", None),
        ("job_ids", "list", None),
        ("base_salary_vnd", "scalar", None),
        ("estimated_income_min_vnd", "scalar", None),
        ("estimated_income_max_vnd", "scalar", None),
        ("allowances", "table", ("name", "amount_vnd", "cadence", "conditions")),
        ("bonuses", "table", ("name", "amount_vnd", "cadence", "conditions")),
        ("overtime_notes", "scalar", None),
        ("payment_notes", "scalar", None),
    )),
    "requirements": ("requirements", (
        ("id", "scalar", None),
        ("job_ids", "list", None),
        ("age_min", "scalar", None),
        ("age_max", "scalar", None),
        ("genders", "list", None),
        ("education", "scalar", None),
        ("experience", "scalar", None),
        ("health", "list", None),
        ("skills", "list", None),
        ("required_documents", "list", None),
        ("other", "list", None),
    )),
    "work_schedules": ("work_schedules", (
        ("id", "scalar", None),
        ("job_ids", "list", None),
        ("work_days", "list", None),
        ("shifts", "table", ("name", "start_time", "end_time", "crosses_midnight")),
        ("rotation", "scalar", None),
        ("breaks", "list", None),
        ("overtime", "scalar", None),
        ("notes", "scalar", None),
    )),
    "benefits": ("benefits", (
        ("id", "scalar", None),
        ("job_ids", "list", None),
        ("name", "scalar", None),
        ("description", "scalar", None),
        ("eligibility", "scalar", None),
    )),
    "accommodation": ("accommodation", (
        ("id", "scalar", None),
        ("job_ids", "list", None),
        ("available", "scalar", None),
        ("type", "scalar", None),
        ("address", "scalar", None),
        ("monthly_cost_vnd", "scalar", None),
        ("deposit_vnd", "scalar", None),
        ("included_services", "list", None),
        ("eligibility", "scalar", None),
        ("notes", "scalar", None),
    )),
    "meals": ("meals", (
        ("id", "scalar", None),
        ("job_ids", "list", None),
        ("provided", "scalar", None),
        ("meals_per_shift", "scalar", None),
        ("allowance_vnd", "scalar", None),
        ("menu_notes", "scalar", None),
        ("eligibility", "scalar", None),
        ("notes", "scalar", None),
    )),
    "transportation": ("transportation", (
        ("id", "scalar", None),
        ("job_ids", "list", None),
        ("name", "scalar", None),
        ("direction", "scalar", None),
        ("service_days", "list", None),
        ("shift", "scalar", None),
        ("fee_vnd", "scalar", None),
        ("stops", "table", ("order", "name", "time", "address")),
        ("notes", "scalar", None),
    )),
    "insurance": ("insurance", (
        ("id", "scalar", None),
        ("job_ids", "list", None),
        ("name", "scalar", None),
        ("provider", "scalar", None),
        ("employee_contribution", "scalar", None),
        ("employer_contribution", "scalar", None),
        ("coverage", "list", None),
        ("starts_after", "scalar", None),
        ("eligibility", "scalar", None),
        ("notes", "scalar", None),
    )),
    "application": ("application", (
        ("id", "scalar", None),
        ("job_ids", "list", None),
        ("application_steps", "list", None),
        ("required_documents", "list", None),
        ("interview_location", "scalar", None),
        ("interview_process", "scalar", None),
        ("onboarding_steps", "list", None),
        ("processing_time", "scalar", None),
        ("fees", "scalar", None),
        ("notes", "scalar", None),
    )),
    "contacts": ("contacts", (
        ("id", "scalar", None),
        ("name", "scalar", None),
        ("role", "scalar", None),
        ("phone", "scalar", None),
        ("zalo", "scalar", None),
        ("email", "scalar", None),
        ("address", "scalar", None),
        ("working_hours", "scalar", None),
        ("notes", "scalar", None),
    )),
    "faq": ("faq", (
        ("id", "scalar", None),
        ("question", "scalar", None),
        ("answer", "scalar", None),
        ("tags", "list", None),
        ("question_variants", "list", None),
        ("required_terms", "list", None),
        ("forbidden_terms", "list", None),
    )),
}


def _encode_scalar(value):
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, str):
        out = value
        for raw, escaped in (("\\", "\\\\"), ('"', '\\"'), ("\n", "\\n"), ("\r", "\\r"), ("\t", "\\t")):
            out = out.replace(raw, escaped)
        return f'"{out}"'
    return str(value)


def _decode_scalar(raw):
    value = raw.strip()
    if value == "null":
        return None
    if value == "true":
        return True
    if value == "false":
        return False
    if len(value) >= 2 and value.startswith('"') and value.endswith('"'):
        out = []
        escaped = False
        for ch in value[1:-1]:
            if escaped:
                out.append({"n": "\n", "r": "\r", "t": "\t", '"': '"', "\\": "\\"}.get(ch, ch))
                escaped = False
            elif ch == "\\":
                escaped = True
            else:
                out.append(ch)
        if escaped:
            out.append("\\")
        return "".join(out)
    if value.startswith("[") and value.endswith("]") and not value[1:-1].strip():
        return []
    if value.lstrip("-").isdigit():
        return int(value)
    return value


def _render_markdown(key, payload):
    """Frozen canonical renderer — byte-identical to build_source_markdown at cutover."""
    list_field, fields = _FIELD_TABLES[key]
    lines = [
        "---",
        f'schema_version: "{payload.get("schema_version", "1.0")}"',
        f"category: {key}",
        "---",
        "",
        f"## {list_field}",
        "",
    ]
    for record in payload.get(list_field) or []:
        lines.append(f"### record: {record['id']}")
        for name, kind, columns in fields:
            if name == "id":
                continue
            value = record.get(name)
            if kind == "scalar":
                lines.append(f"{name}: {_encode_scalar(value)}")
            elif kind == "list":
                if value:
                    lines.append(f"{name}:")
                    lines.extend(f"- {_encode_scalar(item)}" for item in value)
                else:
                    lines.append(f"{name}: []")
            elif value:
                lines.append(f"{name}:")
                lines.append("| " + " | ".join(columns) + " |")
                lines.append("| " + " | ".join("---" for _ in columns) + " |")
                for row in value:
                    cells = " | ".join(_encode_scalar(row.get(col)) for col in columns)
                    lines.append(f"| {cells} |")
            else:
                lines.append(f"{name}: []")
        lines.append("")
    return "\n".join(lines).rstrip("\n") + "\n"


def _parse_markdown(key, text):
    """Frozen parser over the renderer's canonical output (round-trip check only)."""
    list_field, fields = _FIELD_TABLES[key]
    if not text.startswith("---\n"):
        raise RuntimeError(f"{key}: converted markdown lost its front-matter")
    end = text.find("\n---", 4)
    if end == -1:
        raise RuntimeError(f"{key}: converted markdown lost its front-matter delimiter")
    body = text[end + 4 :].lstrip("\n")
    section = f"## {list_field}"
    if not body.startswith(section + "\n"):
        raise RuntimeError(f"{key}: converted markdown lost its {section!r} heading")
    payload = {"schema_version": "1.0", "category": key, list_field: []}
    record = None
    open_list = None
    open_table = None
    columns = ()
    header_seen = False
    for raw in body.split("\n")[1:]:
        line = raw.strip()
        if not line:
            continue
        if line.startswith("### record: "):
            record = {"id": line[len("### record: ") :].strip()}
            payload[list_field].append(record)
            open_list = open_table = None
            header_seen = False
            continue
        if record is None:
            raise RuntimeError(f"{key}: converted markdown has content before the first record")
        if line.startswith("|"):
            cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
            if not header_seen:
                if cells != list(columns):
                    raise RuntimeError(f"{key}: converted markdown broke the {open_table} header")
                header_seen = True
                continue
            if cells and all(cell.strip("-:") == "" for cell in cells):
                continue
            if len(cells) != len(columns):
                raise RuntimeError(f"{key}: converted markdown broke a {open_table} row")
            record[open_table].append(
                {col: _decode_scalar(cell) for col, cell in zip(columns, cells) if cell}
            )
            continue
        if ":" in line and not line.startswith("- "):
            name, _, value = line.partition(":")
            name = name.strip()
            value = value.strip()
            kind = next((k for f_name, k, _ in fields if f_name == name), None)
            if kind is None:
                raise RuntimeError(f"{key}: converted markdown has unknown field {name!r}")
            open_list = open_table = None
            header_seen = False
            if kind == "scalar":
                record[name] = _decode_scalar(value)
                continue
            if value not in ("", "[]"):
                raise RuntimeError(f"{key}: field {name!r} unexpectedly carries an inline value")
            record[name] = []
            if kind == "list":
                open_list = name
            else:
                open_table = name
                columns = next(cols for f_name, k, cols in fields if f_name == name)
            continue
        if line.startswith("- ") and open_list is not None:
            record[open_list].append(_decode_scalar(line[2:]))
            continue
        raise RuntimeError(f"{key}: converted markdown has an unrecognized line: {line[:50]}")
    return payload


def _legacy_category_matches(key, legacy_text):
    """The stored YAML/JSON source must at least agree on which category it is.

    A downgrade restores the column name but leaves markdown in place, so a
    re-upgrade meets already-converted rows: front-matter text is accepted as
   -is (their payload still passes the round-trip check below).
    """
    import json

    if legacy_text.lstrip().startswith("---"):
        return
    try:
        document = json.loads(legacy_text)
    except ValueError:
        document = yaml.safe_load(legacy_text)
    if not isinstance(document, dict):
        raise RuntimeError(f"{key}: legacy source is not a mapping document")
    if document.get("category") != key:
        raise RuntimeError(f"{key}: legacy source category drifts from the row's category")


def _with_declared_defaults(key, payload):
    """Materialize declared-but-absent fields so the round-trip check compares
    information, not key presence. The grammar renders an absent field as its
    empty form (``null`` / ``[]``) and the parser materializes it, and the
    pydantic models treat absent and empty as identical."""
    filled = dict(payload)
    filled.setdefault("schema_version", "1.0")
    filled.setdefault("category", key)
    list_field, fields = _FIELD_TABLES[key]
    filled.setdefault(list_field, [])
    records = []
    for record in filled[list_field]:
        record = dict(record)
        for name, kind, _columns in fields:
            if name != "id":
                record.setdefault(name, None if kind == "scalar" else [])
        records.append(record)
    filled[list_field] = records
    return filled


def upgrade() -> None:
    connection = op.get_bind()
    rows = connection.execute(
        sa.text(
            "SELECT r.id, c.category_key, r.normalized_payload, r.source_yaml "
            "FROM knowledge_category_revisions r "
            "JOIN knowledge_categories c ON c.id = r.category_id"
        )
    ).all()
    # Convert and verify BEFORE the rename: the rename drops the source_yaml
    # name this read depends on, and Postgres rolls the whole transaction back
    # if any conversion below raises.
    op.alter_column(
        "knowledge_category_revisions",
        "source_yaml",
        new_column_name="source_markdown",
        existing_type=sa.Text(),
    )
    updates = []
    for row_id, category_key, payload, legacy in rows:
        key = str(category_key)
        if key not in _FIELD_TABLES:
            raise RuntimeError(f"revision {row_id}: unknown category key {key!r}")
        if payload is None:
            raise RuntimeError(f"revision {row_id}: normalized_payload is missing")
        expected = _with_declared_defaults(key, payload)
        markdown = _render_markdown(key, expected)
        if _parse_markdown(key, markdown) != expected:
            raise RuntimeError(f"revision {row_id}: round-trip payload mismatch")
        _legacy_category_matches(key, legacy)
        updates.append({"id": str(row_id), "md": markdown})
    if updates:
        connection.execute(
            sa.text(
                "UPDATE knowledge_category_revisions SET source_markdown = :md WHERE id = :id"
            ),
            updates,
        )
    connection.execute(
        sa.text(
            "UPDATE knowledge_category_revisions "
            "SET source_filename = regexp_replace(source_filename, '\\.ya?ml$', '.md') "
            "WHERE source_filename ~* '\\.ya?ml$'"
        )
    )
    documents = connection.execute(
        sa.text(
            "SELECT d.id, r.normalized_payload, c.category_key "
            "FROM knowledge_documents d "
            "JOIN knowledge_category_revisions r ON r.id = d.category_revision_id "
            "JOIN knowledge_categories c ON c.id = r.category_id "
            "WHERE d.source = 'category_yaml'"
        )
    ).all()
    document_updates = []
    for document_id, payload, category_key in documents:
        document_updates.append(
            {"id": str(document_id), "md": _render_markdown(str(category_key), payload)}
        )
    if document_updates:
        connection.execute(
            sa.text(
                "UPDATE knowledge_documents SET "
                "raw_text = :md, source = 'category_markdown', mime_type = 'text/markdown', "
                "file_name = regexp_replace(file_name, '\\.ya?ml$', '.md') "
                "WHERE id = :id AND source = 'category_yaml'"
            ),
            document_updates,
        )
    connection.execute(
        sa.text(
            "UPDATE bus_routes SET source_page = 'category_markdown' "
            "WHERE source_page = 'category_yaml'"
        )
    )
    connection.execute(
        sa.text(
            "UPDATE knowledge_chunks SET metadata = jsonb_set(metadata, '{source_page}', "
            "'\"category_markdown\"') WHERE metadata ->> 'source_page' = 'category_yaml'"
        )
    )


def downgrade() -> None:
    connection = op.get_bind()
    connection.execute(
        sa.text(
            "UPDATE bus_routes SET source_page = 'category_yaml' "
            "WHERE source_page = 'category_markdown'"
        )
    )
    connection.execute(
        sa.text(
            "UPDATE knowledge_chunks SET metadata = jsonb_set(metadata, '{source_page}', "
            "'\"category_yaml\"') WHERE metadata ->> 'source_page' = 'category_markdown'"
        )
    )
    connection.execute(
        sa.text(
            "UPDATE knowledge_documents SET source = 'category_yaml', "
            "mime_type = 'application/yaml' WHERE source = 'category_markdown'"
        )
    )
    op.alter_column(
        "knowledge_category_revisions",
        "source_markdown",
        new_column_name="source_yaml",
        existing_type=sa.Text(),
    )
