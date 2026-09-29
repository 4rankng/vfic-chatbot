"""Unit tests for the pre-activation retrieval self-test (retrieval_selftest)."""

from __future__ import annotations

from app.services.knowledge.category_contracts import parse_category_yaml
from app.services.knowledge.category_projections import render_category_units
from app.services.knowledge.retrieval_selftest import (
    RETRIEVAL_SELFTEST_FLOOR,
    retrieval_selftest_failures,
)

FAQ_SOURCE = (
    "category: faq\n"
    "faq:\n"
    "  - id: shift-hours\n"
    "    question: Ca làm việc mấy giờ?\n"
    "    answer: Ca ngày 08:00-20:00, ca đêm 20:00-08:00.\n"
)

JOBS_SOURCE = (
    "category: jobs\n"
    "jobs:\n"
    "  - id: assembler\n"
    "    title: Công nhân lắp ráp\n"
    "    location: Hải Phòng\n"
    "    summary: Chi tiết dài chỉ thuộc về vị trí tuyển dụng.\n"
)


class _MappedEmbedder:
    """Returns preset vectors; unknown texts embed as all-zeros."""

    def __init__(self, vectors: dict[str, list[float]]) -> None:
        self.vectors = vectors
        self.batched: list[list[str]] = []

    async def batch(self, texts: list[str]) -> list[list[float]]:
        self.batched.append(texts)
        return [self.vectors.get(text, [0.0]) for text in texts]


async def test_passes_when_each_question_retrieves_its_own_record() -> None:
    document = parse_category_yaml("faq", FAQ_SOURCE)
    units = render_category_units(document)
    # The question and its record content share one vector: perfect retrieval.
    shared = [1.0, 0.0, 0.0]
    embedder = _MappedEmbedder(
        {
            "Ca làm việc mấy giờ?": shared,
            units[0]["content"]: shared,
        }
    )

    failures = await retrieval_selftest_failures(
        document, units, [shared], embedder
    )

    assert failures == []
    # Exactly the question surface was embedded, once.
    assert embedder.batched == [["Ca làm việc mấy giờ?"]]


async def test_fails_with_question_and_similarity_when_record_is_unreachable() -> None:
    document = parse_category_yaml("faq", FAQ_SOURCE)
    units = render_category_units(document)
    orthogonal = [0.0, 0.0, 1.0]
    embedder = _MappedEmbedder({"Ca làm việc mấy giờ?": orthogonal})

    failures = await retrieval_selftest_failures(
        document, units, [[1.0, 0.0, 0.0]], embedder
    )

    assert len(failures) == 1
    assert "Ca làm việc mấy giờ?" in failures[0]
    assert "0.00" in failures[0]
    assert f"{RETRIEVAL_SELFTEST_FLOOR:.2f}" in failures[0]


async def test_jobs_records_query_on_the_title_fallback() -> None:
    document = parse_category_yaml("jobs", JOBS_SOURCE)
    units = render_category_units(document)
    shared = [0.5, 0.5]
    embedder = _MappedEmbedder(
        {
            "Công nhân lắp ráp": shared,
            units[0]["content"]: shared,
        }
    )

    failures = await retrieval_selftest_failures(
        document, units, [shared], embedder
    )

    assert failures == []
    assert embedder.batched == [["Công nhân lắp ráp"]]
