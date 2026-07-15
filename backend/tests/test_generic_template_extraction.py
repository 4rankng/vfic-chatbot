"""Deterministic multi-record extraction for compiler-v2 artifacts."""

from __future__ import annotations

from app.services.ingestion.generic_extraction import extract_compiled_records
from app.services.ingestion.source_blocks import EvidenceLocator, SourceBlock, source_blocks_from_rows
from app.services.ingestion.template_compiler import compile_template


def _artifact(mode: str) -> dict:
    artifact, _ = compile_template(
        {
            "schema_version": "2",
            "record_types": [
                {
                    "key": "item",
                    "display_name": "Item",
                    "occurrence_mode": mode,
                    "max_records": 10 if mode != "single" else 1,
                    "natural_key_fields": ["code"],
                    "fields": [
                        {"key": "code", "type": "string", "aliases": ["Code"], "required": True},
                        {"key": "name", "type": "string", "aliases": ["Name"], "required": True},
                    ],
                }
            ],
        }
    )
    return artifact


def _section(text: str, occurrence_id: str) -> SourceBlock:
    return SourceBlock(
        original_text=text,
        normalized_text=text,
        locator=EvidenceLocator(
            coordinate_space="text",
            source_checksum="a" * 64,
            occurrence_id=occurrence_id,
        ),
    )


def test_repeated_sections_materialize_one_record_per_section_with_exact_evidence():
    records, issues = extract_compiled_records(
        _artifact("repeated_section"),
        [_section("Code: A\nName: Alpha", "first"), _section("Code: B\nName: Beta", "second")],
    )

    assert issues == []
    assert [record.payload for record in records] == [
        {"code": "A", "name": "Alpha"},
        {"code": "B", "name": "Beta"},
    ]
    assert records[0].evidence["code"].occurrence_id == "first"
    assert records[1].evidence["name"].occurrence_id == "second"


def test_table_rows_materialize_each_row_without_llm_or_last_write_wins():
    blocks = source_blocks_from_rows(
        sheet_name="Items",
        headers=["Code", "Name"],
        rows=[["A", "Alpha"], ["B", "Beta"]],
        source_checksum="b" * 64,
    )

    records, issues = extract_compiled_records(_artifact("table_rows"), blocks)

    assert issues == []
    assert [record.payload["code"] for record in records] == ["A", "B"]
    assert [record.evidence["name"].row_start for record in records] == [2, 3]


def test_single_occurrence_conflicts_require_review_instead_of_arbitrary_selection():
    records, issues = extract_compiled_records(
        _artifact("single"),
        [_section("Code: A", "first"), _section("Code: B\nName: Beta", "second")],
    )

    assert records == []
    assert [issue.code for issue in issues] == ["conflicting_source_value"]
