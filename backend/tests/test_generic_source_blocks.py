"""Characterization tests for coordinate-preserving, domain-neutral sources."""

from __future__ import annotations

import hashlib

import pytest

from app.services.ingestion.limits import (
    MAX_UPLOAD_BYTES,
    IngestionLimitError,
    assert_upload_size,
    bounded_batches,
)
from app.services.ingestion.source_blocks import (
    source_blocks_from_rows,
    source_blocks_from_sections,
    source_blocks_from_text,
)


def test_text_blocks_preserve_original_text_normalized_text_and_coordinates():
    source = "Tên\r\nKha\u0301ch ha\u0300ng: Công ty A\r\nMã: A-01\n"
    checksum = hashlib.sha256(source.encode()).hexdigest()

    blocks = source_blocks_from_text(source)

    assert [block.locator.line_start for block in blocks] == [1, 2, 3]
    assert blocks[0].original_text == "Tên"
    assert blocks[1].normalized_text == "Khách hàng: Công ty A"
    assert blocks[1].locator.coordinate_space == "text"
    assert blocks[1].locator.source_checksum == checksum
    assert blocks[1].locator.normalized_offset_map


def test_tabular_blocks_preserve_sheet_row_column_evidence():
    blocks = source_blocks_from_rows(
        sheet_name="Sản phẩm",
        headers=["SKU", "Tên"],
        rows=[["SP-01", "Áo khoác"], ["", ""]],
        source_checksum="a" * 64,
    )

    assert len(blocks) == 1
    assert blocks[0].locator.coordinate_space == "sheet"
    assert blocks[0].locator.sheet == "Sản phẩm"
    assert blocks[0].locator.row_start == 2
    assert blocks[0].locator.column_start == 1
    assert blocks[0].normalized_text == "SKU: SP-01\nTên: Áo khoác"


def test_section_blocks_preserve_multiline_records_and_original_offsets():
    blocks = source_blocks_from_sections("Code: A\r\nName: Alpha\r\n\r\nCode: B\nName: Beta")

    assert [block.normalized_text for block in blocks] == [
        "Code: A\nName: Alpha",
        "Code: B\nName: Beta",
    ]
    assert [block.locator.occurrence_id for block in blocks] == ["section:1", "section:2"]
    assert blocks[0].locator.start_offset == 0


def test_code_owned_upload_limit_and_batching_cannot_be_expanded_by_callers():
    assert_upload_size(MAX_UPLOAD_BYTES)
    with pytest.raises(IngestionLimitError, match="upload exceeds"):
        assert_upload_size(MAX_UPLOAD_BYTES + 1)

    assert list(bounded_batches(range(11), batch_size=10)) == [list(range(10)), [10]]
    with pytest.raises(IngestionLimitError, match="batch size"):
        list(bounded_batches(range(1), batch_size=11))
