from app.services.knowledge.text_ingestion import (
    chunk_type_from_metadata,
    canonical_kb_text_stats,
    estimate_token_count,
    kb_text_stats,
    line_range_for_quote,
    make_content_plain,
    normalize_kb_text,
    normalize_kb_value,
    section_path_from_metadata,
)


def test_kb_text_stats_normalizes_line_endings_and_hashes_normalized_text():
    stats = kb_text_stats("\ufeffDòng 1\r\n\r\n\r\n\r\nDòng 2\r")

    assert stats.normalized_text == "Dòng 1\n\n\nDòng 2"
    assert stats.char_count == len(stats.normalized_text)
    assert stats.line_count == 4
    assert len(stats.content_sha256) == 64


def test_recursive_normalization_is_idempotent_and_preserves_scalar_types():
    decomposed = "Ca\u0301 đêm  "
    value = {
        "name": decomposed,
        "lines": ["Một  \r\nHai\t ", 42, True, None],
    }

    normalized = normalize_kb_value(value)

    assert normalized == {
        "name": "Cá đêm",
        "lines": ["Một\nHai", 42, True, None],
    }
    assert normalize_kb_value(normalized) == normalized
    assert normalize_kb_text(decomposed) == "Cá đêm"


def test_canonical_line_cleanup_does_not_change_legacy_markdown_hard_breaks():
    markdown = "Dòng một  \nDòng hai"

    assert normalize_kb_text(markdown) == markdown
    assert canonical_kb_text_stats(markdown).normalized_text == "Dòng một\nDòng hai"


def test_line_range_for_quote_returns_one_based_range():
    source = "# Title\n\n## Salary\nLương 10 triệu\nPhụ cấp ca đêm\n\n## FAQ\nA"

    assert line_range_for_quote(source, "Lương 10 triệu\nPhụ cấp ca đêm") == (4, 5)


def test_line_range_for_quote_tolerates_whitespace_differences():
    source = "Area: Thủ Đức\nPickup point: Vincom\nShift: 06:00"

    assert line_range_for_quote(source, "Area: Thủ Đức Pickup point: Vincom") == (1, 2)


def test_metadata_helpers_extract_section_path_and_chunk_type():
    metadata = {
        "chunk_metadata": {
            "breadcrumb": "LG Display > Bus Routes",
            "content_type": "company_knowledge",
            "route_id": "td_plaza",
        }
    }

    assert section_path_from_metadata(metadata) == ["LG Display", "Bus Routes"]
    assert chunk_type_from_metadata(metadata, "schedule") == "markdown_table"


def test_content_plain_and_token_count_are_deterministic():
    assert make_content_plain("Ca đêm", "Thủ Đức") == "ca dem thu duc"
    assert estimate_token_count("Ca đêm\nThủ Đức") == 4
