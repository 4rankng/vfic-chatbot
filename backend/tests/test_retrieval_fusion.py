from types import SimpleNamespace

from app.services.retrieval.fusion import reciprocal_rank_fuse


def _row(row_id: int) -> SimpleNamespace:
    return SimpleNamespace(id=row_id)


def test_rrf_rewards_evidence_found_by_both_retrievers() -> None:
    rows = reciprocal_rank_fuse([_row(1), _row(2)], [_row(2), _row(3)], top_k=3)

    assert [row.id for row in rows] == [2, 1, 3]


def test_rrf_deduplicates_and_respects_limit() -> None:
    rows = reciprocal_rank_fuse([_row(1), _row(2)], [_row(1), _row(3)], top_k=2)

    assert [row.id for row in rows] == [1, 2]


def test_rrf_ignores_uncitable_rows() -> None:
    rows = reciprocal_rank_fuse([SimpleNamespace()], [_row(2)], top_k=3)

    assert [row.id for row in rows] == [2]
