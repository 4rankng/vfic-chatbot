"""Characterization tests for the canonical knowledge Markdown parser + repair pass.

These pin the current behavior of ``parse_canonical_markdown`` and
``repair_canonical_markdown`` so the bus-timetable repair cluster can be extracted
into its own module without silently changing parser outcomes.
"""

from __future__ import annotations

import pytest

from app.services.knowledge.canonical import (
    CANONICAL_SCHEMA_VERSIONS,
    CanonicalValidationError,
    FAQ_SCHEMA_VERSION,
    SCHEMA_VERSION,
    build_contextual_text,
    checksum_text,
    load_template,
    parse_canonical_markdown,
)
from app.services.knowledge.bus_timetable.repair import repair_canonical_markdown


# ── Fixtures ──────────────────────────────────────────────────────────────


def _render_frontmatter(fields: dict) -> str:
    lines = ["---"]
    for key, value in fields.items():
        if isinstance(value, list):
            lines.append(f"{key}:")
            for item in value:
                lines.append(f"  - {item}")
        elif value is None:
            lines.append(f"{key}: null")
        elif isinstance(value, bool):
            lines.append(f"{key}: {str(value).lower()}")
        elif isinstance(value, int):
            lines.append(f"{key}: {value}")
        else:
            lines.append(f'{key}: "{value}"')
    lines.append("---")
    return "\n".join(lines) + "\n"


def _base_frontmatter(**overrides) -> dict:
    fields = {
        "schema_version": SCHEMA_VERSION,
        "doc_id": "doc_test",
        "doc_version": 1,
        "title": "Test Doc",
        "company_name": "TestCo",
        "project_slug": "test",
        "locale": "vi",
        "audience": ["worker"],
        "content_type": "company_knowledge",
        "effective_from": "2026-01-01",
        "source_owner": "ops",
    }
    fields.update(overrides)
    return fields


def _full_body() -> str:
    return (
        "\n"
        "## Company Overview\n\nOverview text.\n\n"
        "## Worker Features\n\n"
        "### Feature: take_home_income\n\nQuestion: Q1?\n\nAnswer: A1.\n\n"
        "## Rules/Policies\n\nA policy.\n\n"
        "## FAQ\n\n### FAQ: Something\n\nQuestion: Q2?\n\nAnswer: A2.\n\n"
        "## Contacts\n\nContact details.\n"
    )


def _doc(**overrides) -> str:
    return _render_frontmatter(_base_frontmatter(**overrides)) + _full_body()


def _bus_route_block(*, service_days: str, table_rows: str) -> str:
    return (
        "### Bus Route: Test route\n\n"
        "route_id: test\n"
        "route_group: Test\n"
        "route_name: Test\n"
        "shift: day\n"
        "direction: outbound\n\n"
        f"service_days:\n{service_days}\n\n"
        "| stop_order | stop_name | aliases | scheduled_time | notes |\n"
        "|---|---|---|---|---|\n"
        f"{table_rows}\n"
    )


# ── parse_canonical_markdown: happy paths ─────────────────────────────────


def test_parse_full_template_document():
    doc = parse_canonical_markdown(load_template())

    assert doc.metadata["schema_version"] == SCHEMA_VERSION
    assert doc.metadata["title"] == "LG Display Worker Guide"
    assert doc.metadata["audience"] == ["worker", "customer"]
    assert doc.checksum.startswith("sha256:") and len(doc.checksum) == 7 + 64
    # Company overview + 11 active feature chunks + policy + faq + contacts + bus routes
    assert len(doc.chunks) == 16
    categories = sorted({chunk.category for chunk in doc.chunks})
    assert categories == ["contact", "faq", "feature", "job", "policy", "schedule"]
    job_chunk = next(chunk for chunk in doc.chunks if chunk.category == "job")
    assert job_chunk.entities["job_title"] == "temporary workers"
    assert len(doc.bus_timetable.routes) == 1
    # 4 service-day lines × 5 service flags each
    assert len(doc.bus_timetable.service_days) == 20


def test_parse_minimal_valid_document():
    doc = parse_canonical_markdown(_doc())
    assert doc.document_summary == "Test Doc"
    # company overview + 1 feature + policy + faq + contacts (no bus routes section)
    assert len(doc.chunks) == 5
    assert {chunk.category for chunk in doc.chunks} == {
        "job",
        "feature",
        "policy",
        "faq",
        "contact",
    }
    assert doc.bus_timetable.routes == []


def test_parse_faq_schema_document():
    fields = _base_frontmatter(schema_version=FAQ_SCHEMA_VERSION, content_type="faq")
    body = "\n## FAQ\n\n### FAQ: Greeting\n\nQuestion: Xin chao?\n\nAnswer: Chao ban.\n"
    doc = parse_canonical_markdown(_render_frontmatter(fields) + body)
    assert doc.metadata["schema_version"] == FAQ_SCHEMA_VERSION
    assert len(doc.chunks) == 1
    assert doc.chunks[0].category == "faq"
    assert doc.bus_timetable.routes == []


def test_parse_checksum_is_stable_and_idempotent():
    text = _doc()
    first = parse_canonical_markdown(text)
    second = parse_canonical_markdown(text)
    assert first.checksum == second.checksum == checksum_text(text.replace("\r\n", "\n"))


def test_parse_normalizes_crlf_and_bom():
    text = "﻿" + _doc().replace("\n", "\r\n")
    doc = parse_canonical_markdown(text)
    assert doc.checksum == checksum_text(_doc())


# ── parse_canonical_markdown: validation errors ───────────────────────────


def _errors_for(text: str) -> list[str]:
    with pytest.raises(CanonicalValidationError) as exc_info:
        parse_canonical_markdown(text)
    return exc_info.value.errors


def test_parse_rejects_missing_frontmatter():
    errors = _errors_for("no frontmatter here")
    assert any("frontmatter" in err.lower() for err in errors)


def test_parse_rejects_unknown_schema_version():
    errors = _errors_for(_doc(schema_version="bogus-v9"))
    assert any("schema_version" in err for err in errors)


def test_parse_rejects_missing_required_frontmatter_key():
    fields = _base_frontmatter()
    del fields["company_name"]
    errors = _errors_for(_render_frontmatter(fields) + _full_body())
    assert any("company_name" in err for err in errors)


def test_parse_rejects_non_list_audience():
    errors = _errors_for(_doc(audience="worker"))  # rendered as a scalar string
    assert any("audience" in err for err in errors)


def test_parse_rejects_bad_effective_from_format():
    errors = _errors_for(_doc(effective_from="01-01-2026"))
    assert any("effective_from" in err for err in errors)


def test_parse_rejects_missing_required_section():
    # All required sections except FAQ.
    body = (
        "\n## Company Overview\n\nx\n\n## Worker Features\n\n"
        "### Feature: take_home_income\n\nQuestion: Q?\n\nAnswer: A.\n\n"
        "## Rules/Policies\n\nx\n\n## Contacts\n\nx\n"
    )
    errors = _errors_for(_render_frontmatter(_base_frontmatter()) + body)
    assert any("FAQ" in err for err in errors)


def test_parse_rejects_empty_required_section():
    body = (
        "\n## Company Overview\n\nx\n\n"
        "## Worker Features\n\n\n\n"  # empty
        "## Rules/Policies\n\nx\n\n## FAQ\n\n### FAQ: X\n\nQuestion: Q?\n\nAnswer: A.\n\n"
        "## Contacts\n\nx\n"
    )
    errors = _errors_for(_render_frontmatter(_base_frontmatter()) + body)
    assert any("Worker Features" in err for err in errors)


def test_parse_rejects_unknown_feature_key():
    body = (
        "\n## Company Overview\n\nx\n\n## Worker Features\n\n"
        "### Feature: bogus_key\n\nQuestion: Q?\n\nAnswer: A.\n\n"
        "## Rules/Policies\n\nx\n\n## FAQ\n\n### FAQ: X\n\nQuestion: Q?\n\nAnswer: A.\n\n"
        "## Contacts\n\nx\n"
    )
    errors = _errors_for(_render_frontmatter(_base_frontmatter()) + body)
    assert any("bogus_key" in err for err in errors)


def test_parse_silently_drops_bus_route_with_bad_scheduled_time():
    # Bus-route validation errors are collected locally and the offending route is
    # skipped rather than failing the whole document parse.
    block = _bus_route_block(
        service_days="- mon_thu: outbound_admin_and_day=A",
        table_rows="| 1 | Stop A | A | 6:15 | note |",
    )
    text = _doc() + "\n## Bus Routes\n\n" + block
    doc = parse_canonical_markdown(text)
    assert doc.bus_timetable.routes == []


def test_parse_silently_drops_bus_route_with_unknown_service_day():
    block = _bus_route_block(
        service_days="- weekday: outbound_admin_and_day=A",
        table_rows="| 1 | Stop A | A | 06:15 | note |",
    )
    text = _doc() + "\n## Bus Routes\n\n" + block
    doc = parse_canonical_markdown(text)
    assert doc.bus_timetable.routes == []


# ── repair_canonical_markdown ─────────────────────────────────────────────


def test_repair_is_noop_without_bus_route_blocks():
    text = _doc()
    result = repair_canonical_markdown(text)
    assert not result.changed
    assert result.repairs == []
    assert result.text == text


def test_repair_is_noop_for_already_valid_bus_route():
    block = _bus_route_block(
        service_days="- mon_thu: outbound_admin_and_day=A",
        table_rows="| 1 | Stop A | A | 06:15 | note |",
    )
    text = (
        "### Bus Route: R\n\nroute_id: r\nroute_group: G\nroute_name: R\nshift: day\ndirection: outbound\n\n"
        + block.split("### Bus Route: Test route\n\n", 1)[1]
    )
    result = repair_canonical_markdown(text)
    assert not result.changed
    assert result.repairs == []


def test_repair_applies_all_three_repair_codes():
    block = _bus_route_block(
        service_days=("- mon_thu: not applicable\n- fri: outbound_admin_and_day=A, return_night=M"),
        table_rows=("| 1 | Stop A | A | 6:15 |  |\n| 2 | Stop B | B | 06:30 or 06:45 |  |"),
    )
    result = repair_canonical_markdown(block)
    assert result.changed
    codes = {repair["code"] for repair in result.repairs}
    assert codes == {
        "drop_prose_service_days",
        "pad_scheduled_time",
        "move_non_scalar_scheduled_time_to_notes",
    }
    # Single-digit hour was zero-padded.
    assert "| 06:15 |" in result.text
    assert "| 6:15 |" not in result.text
    # Non-scalar time was moved into the notes cell.
    assert "Scheduled time note: 06:30 or 06:45." in result.text
    # Prose service_days line was dropped, valid one kept.
    assert "not applicable" not in result.text
    assert "return_night=M" in result.text


def test_repair_leaves_non_time_scheduled_value_untouched():
    block = _bus_route_block(
        service_days="- mon_thu: outbound_admin_and_day=A",
        table_rows="| 1 | Stop A | A | see notes | note |",
    )
    result = repair_canonical_markdown(block)
    # No recognizable HH:MM pattern and not a padable single-digit time → no repair.
    assert not any(r["code"] == "pad_scheduled_time" for r in result.repairs)
    assert not any(r["code"] == "move_non_scalar_scheduled_time_to_notes" for r in result.repairs)


def test_repair_ignores_table_with_unexpected_headers():
    block = (
        "### Bus Route: R\n\n"
        "route_id: r\nroute_group: G\nroute_name: R\nshift: day\ndirection: outbound\n\n"
        "service_days:\n- mon_thu: outbound_admin_and_day=A\n\n"
        "| col_a | col_b |\n"
        "|---|---|\n"
        "| 1 | 06:15 |\n"
    )
    result = repair_canonical_markdown(block)
    assert not any(r["code"] == "pad_scheduled_time" for r in result.repairs)


def test_repair_then_parse_round_trip():
    """Without repair a single-digit scheduled_time makes the route get dropped;
    after repair the route is retained with a real scheduled_time."""
    block = _bus_route_block(
        service_days="- mon_thu: outbound_admin_and_day=A",
        table_rows="| 1 | Stop A | A | 6:15 | note |",
    )
    text = _doc() + "\n## Bus Routes\n\n" + block
    # Direct parse silently drops the route.
    assert parse_canonical_markdown(text).bus_timetable.routes == []
    # After repair, the route is retained.
    repaired = repair_canonical_markdown(text)
    assert repaired.changed
    doc = parse_canonical_markdown(repaired.text)
    assert len(doc.bus_timetable.routes) == 1
    assert doc.bus_timetable.routes[0].stops[0].scheduled_time is not None


# ── build_contextual_text + to_unit ───────────────────────────────────────


def test_build_contextual_text_shape():
    doc = parse_canonical_markdown(_doc())
    chunk = next(c for c in doc.chunks if c.category == "job")
    context = build_contextual_text(doc, chunk)
    assert "Document: Test Doc" in context
    assert "Company: TestCo" in context
    assert "Section:" in context
    assert chunk.content in context


def test_chunk_to_unit_metadata_shape():
    doc = parse_canonical_markdown(_doc())
    chunk = next(c for c in doc.chunks if c.category == "faq")
    unit = chunk.to_unit(doc)
    assert unit["category"] == "faq"
    assert unit["confidence"] == "high"
    assert unit["is_inference"] is False
    assert unit["metadata"]["document_metadata"]["doc_id"] == "doc_test"
    assert unit["metadata"]["citation"]["source_anchor"] == chunk.citation.source_anchor
    assert unit["contextual_text"]


def test_schema_version_set_is_exported():
    assert SCHEMA_VERSION in CANONICAL_SCHEMA_VERSIONS
    assert FAQ_SCHEMA_VERSION in CANONICAL_SCHEMA_VERSIONS
