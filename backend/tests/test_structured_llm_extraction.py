from __future__ import annotations

import pytest

from app.services.ingestion.source_blocks import source_blocks_from_sections
from app.services.ingestion.structured_llm_extraction import (
    StructuredLlmExtractionError,
    bounded_unresolved_batches,
    verify_sourced_fields,
)


def test_llm_fallback_is_bounded_and_requires_exact_source_quote():
    blocks = source_blocks_from_sections("code: A\nname: Alpha")
    assert len(bounded_unresolved_batches(blocks)) == 1
    assert verify_sourced_fields(
        {"records": [{"record_type_key": "item", "fields": [{"key": "name", "value": "Alpha", "occurrence_id": "section:1", "quote": "name: Alpha"}]}]},
        blocks=blocks,
    ) == [{"record_type_key": "item", "fields": {"name": "Alpha"}}]
    with pytest.raises(StructuredLlmExtractionError, match="does not match"):
        verify_sourced_fields(
            {"records": [{"record_type_key": "item", "fields": [{"key": "name", "value": "Alpha", "occurrence_id": "section:1", "quote": "invented"}]}]},
            blocks=blocks,
        )
