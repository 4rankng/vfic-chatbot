from types import SimpleNamespace

from app.services.retrieval.fusion import reciprocal_rank_fuse
from app.services.retrieval.repository import RetrievalRepository


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


def test_chunk_visibility_requires_active_category_revision_and_gates_legacy() -> None:
    predicate = RetrievalRepository._chunk_visibility("")

    assert "p.category_authority_started IS TRUE" in predicate
    assert "kc.project_id = p.id AND kc.active_revision_id = kr.id" in predicate
    assert "kr.id = c.category_revision_id" in predicate
    assert "d.category_revision_id = kr.id" in predicate
    assert "c.category_revision_id IS NULL" in predicate
    assert "c.kb_version_id = p.active_kb_version_id" in predicate
    assert "p.category_authority_started IS FALSE" in predicate
    assert "d.status NOT IN ('ARCHIVED', 'FAILED')" in predicate
