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

# The defect this gate's skip exists for: real job briefs list whole crews by
# role acronym. Every title here is under five letters, so none is testable by
# title alone.
JOBS_ACRONYM_SOURCE = (
    "category: jobs\n"
    "jobs:\n"
    "  - id: qa\n"
    "    title: QA\n"
    "    location: Hải Phòng\n"
    "    summary: Kiểm tra chất lượng linh kiện điện tử.\n"
    "  - id: smt\n"
    "    title: SMT\n"
    "    location: Hải Phòng\n"
    "    summary: Vận hành máy dán linh kiện bề mặt.\n"
    "  - id: ui\n"
    "    title: UI\n"
    "    location: Hải Phòng\n"
    "    summary: Thiết kế giao diện sản phẩm.\n"
    "  - id: mv\n"
    "    title: MV\n"
    "    location: Hải Phòng\n"
    "    summary: Kiểm tra sản phẩm bằng thị giác máy.\n"
)

# One acronym next to one normal-length title: the skip must cover the short
# query and nothing else.
JOBS_MIXED_SOURCE = (
    "category: jobs\n"
    "jobs:\n"
    "  - id: qa\n"
    "    title: QA\n"
    "    location: Hải Phòng\n"
    "    summary: Kiểm tra chất lượng linh kiện điện tử.\n"
    "  - id: quality-engineer\n"
    "    title: Kỹ sư kiểm định chất lượng\n"
    "    location: Hải Phòng\n"
    "    summary: Đánh giá quy trình kiểm định của nhà máy.\n"
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


async def test_acronym_role_titles_are_skipped_not_failed() -> None:
    """Role acronyms ("QA", "SMT", "UI", "MV") cannot self-retrieve by title
    alone — the title embedding is noise at that length — so the gate skips
    them instead of failing the whole category over them."""
    document = parse_category_yaml("jobs", JOBS_ACRONYM_SOURCE)
    units = render_category_units(document)
    # Every content vector sits opposite the vector the acronyms would embed
    # to: without the skip each title would report best similarity 0.00 and
    # the category would die. With the skip, no query is embedded at all.
    embedder = _MappedEmbedder(
        {
            "QA": [1.0, 0.0],
            "SMT": [1.0, 0.0],
            "UI": [1.0, 0.0],
            "MV": [1.0, 0.0],
        }
    )

    failures = await retrieval_selftest_failures(
        document, units, [[0.0, 1.0]] * len(units), embedder
    )

    assert failures == []
    # Untestable queries never reach the embedder — no spend, no signal.
    assert embedder.batched == []


async def test_a_long_title_that_cannot_retrieve_its_record_still_fails() -> None:
    """The skip covers untestable short queries only: a normal-length title
    whose content disagrees semantically still fails the gate."""
    document = parse_category_yaml("jobs", JOBS_SOURCE)
    units = render_category_units(document)
    orthogonal = [0.0, 0.0, 1.0]
    embedder = _MappedEmbedder({"Công nhân lắp ráp": orthogonal})

    failures = await retrieval_selftest_failures(
        document, units, [[1.0, 0.0, 0.0]], embedder
    )

    assert len(failures) == 1
    assert "Công nhân lắp ráp" in failures[0]
    assert "0.00" in failures[0]
    assert f"{RETRIEVAL_SELFTEST_FLOOR:.2f}" in failures[0]


async def test_short_queries_are_skipped_while_the_long_one_still_fails() -> None:
    """Mixed document: the acronym is outside the gate's reach, the
    normal-length title right next to it is judged at full strictness."""
    document = parse_category_yaml("jobs", JOBS_MIXED_SOURCE)
    units = render_category_units(document)
    embedder = _MappedEmbedder({"Kỹ sư kiểm định chất lượng": [1.0, 0.0]})

    failures = await retrieval_selftest_failures(
        document, units, [[0.0, 1.0], [0.0, 1.0]], embedder
    )

    assert len(failures) == 1
    assert "Kỹ sư kiểm định chất lượng" in failures[0]
    assert "QA" not in failures[0]
    # Only the testable title was embedded.
    assert embedder.batched == [["Kỹ sư kiểm định chất lượng"]]
