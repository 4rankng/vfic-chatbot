"""Tests for ``category_service._render_units`` — the chunk-construction path
that turns a validated ``CategoryDocument`` into the embedder input plus chunk
metadata.

These pin the FAQ tag-forwarding contract: per-item tags (section /
sub-category from the source sheet) reach both the embedder input (as a
deterministic trailing ``Tags:`` line) and ``chunk_metadata.tags`` (parity with
``canonical.to_unit``), without disturbing non-FAQ categories. Tags keep the
parser's emission order (broad section → specific sub-category); they are
preserved, not re-sorted.
"""

from __future__ import annotations

from app.schemas.knowledge_categories import FaqDocument, JobsDocument
from app.services.knowledge.category_service import _render_units


def _faq_doc(tags: list[str]) -> FaqDocument:
    return FaqDocument(
        faq=[{"id": "q1", "question": "Q1?", "answer": "A1", "tags": tags}]
    )


def test_render_units_forwards_tags_into_chunk_metadata() -> None:
    units = _render_units(_faq_doc(["alpha", "beta"]))

    assert units[0]["metadata"]["chunk_metadata"]["tags"] == ["alpha", "beta"]


def test_render_units_appends_tags_line_to_content() -> None:
    units = _render_units(_faq_doc(["alpha", "beta"]))
    content = units[0]["content"]

    assert "Tags: alpha, beta" in content
    # Tags are popped out of the generic field dump, so the raw JSON-array form
    # must not ALSO appear mid-content (it would be a duplicate, in arbitrary
    # field order).
    assert "tags: [" not in content


def test_render_units_preserves_tag_order() -> None:
    """Tag order is preserved as-is; _render_units does NOT re-sort. Re-sorting
    would discard the parser's semantic broad→specific ordering, and the parser
    output is already deterministic."""
    units = _render_units(_faq_doc(["zeta", "alpha"]))

    assert units[0]["metadata"]["chunk_metadata"]["tags"] == ["zeta", "alpha"]
    assert "Tags: zeta, alpha" in units[0]["content"]


def test_render_units_omits_tags_line_when_empty() -> None:
    """An FAQ item with no tags renders with no ``Tags:`` line and an empty
    ``chunk_metadata.tags`` list."""
    units = _render_units(_faq_doc([]))

    assert "Tags:" not in units[0]["content"]
    assert units[0]["metadata"]["chunk_metadata"]["tags"] == []


def test_render_units_leaves_non_faq_categories_untouched() -> None:
    """Non-FAQ categories have no ``tags`` field: no ``Tags:`` line in content
    and no ``chunk_metadata`` key (only the FAQ branch adds one)."""
    doc = JobsDocument(jobs=[{"id": "j1", "title": "Nhân viên"}])
    units = _render_units(doc)

    assert len(units) == 1
    assert "Tags:" not in units[0]["content"]
    assert "chunk_metadata" not in units[0]["metadata"]


def test_render_units_supports_multiple_faq_items() -> None:
    """Each item carries its own tags independently through the render path."""
    doc = FaqDocument(
        faq=[
            {"id": "q1", "question": "Q1?", "answer": "A1", "tags": ["Độ tuổi"]},
            {"id": "q2", "question": "Q2?", "answer": "A2", "tags": []},
        ]
    )
    units = _render_units(doc)

    assert units[0]["metadata"]["chunk_metadata"]["tags"] == ["Độ tuổi"]
    assert "Tags: Độ tuổi" in units[0]["content"]
    assert units[1]["metadata"]["chunk_metadata"]["tags"] == []
    assert "Tags:" not in units[1]["content"]
