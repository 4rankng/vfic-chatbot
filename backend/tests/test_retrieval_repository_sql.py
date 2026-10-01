"""Characterization of retrieval SQL shape properties without a live DB.

Two properties are pinned:

* the ANN vector query computes the exact distance ONCE per candidate row --
  an inner ``dist`` alias feeds both the floor predicate and the ORDER BY --
  while candidate selection keeps the halfvec(3072) cast that matches the
  HNSW index expression;
* the memories fast path casts to halfvec(3072) so its HNSW index expression
  matches (the general-filter path delegates to the SQL ``match_memories``
  function, whose halfvec typing and index selection are proven against a
  live database in ``tests/integration/test_memories_halfvec_index.py``);
* ``active_project_ids`` sorts deterministically so the RAG cache digest
  cannot depend on heap row order.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services.retrieval import document_repository, repository


class _EmptyResult:
    """Mimics the SQLAlchemy Result wrapper (.all())."""

    @staticmethod
    def all() -> list:
        return []


class _CaptureExecDb:
    """Async stand-in for AsyncSession.execute() that records each call."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    async def execute(self, stmt, params=None):
        self.calls.append((str(stmt), dict(params or {})))
        return _EmptyResult()


class _ScalarsDb:
    """Async stand-in for AsyncSession.scalars() recording the statement."""

    def __init__(self) -> None:
        self.last_statement = ""

    async def scalars(self, stmt):
        self.last_statement = str(stmt)
        return iter(())


def _ann_settings() -> SimpleNamespace:
    return SimpleNamespace(
        rag_ann_enabled=True,
        embedding_dim=document_repository.EMBEDDING_DIM,
        rag_ann_candidates=200,
    )


@pytest.mark.asyncio
async def test_ann_query_computes_distance_once(monkeypatch):
    """The exact distance is computed once and reused by floor + ORDER BY."""
    monkeypatch.setattr(document_repository, "get_settings", lambda: _ann_settings())
    db = _CaptureExecDb()
    repo = document_repository.DocumentRepository(db)
    await repo._match_document_vector_rows(
        emb="e", top_k=5, filter_json="{}", project_clause="", project_ids=None
    )
    sql, params = db.calls[0]
    # The distance expression appears exactly once (previously three times).
    assert sql.count("CAST(:emb AS vector)") == 1
    # Floor + ORDER BY reference the single computed distance.
    assert "WHERE dist <= :max_dist" in sql
    assert "ORDER BY dist" in sql
    assert params["max_dist"] == 1 - document_repository.DocumentRepository.SIMILARITY_FLOOR
    assert "floor" not in params
    # Candidate selection keeps the halfvec cast that matches the HNSW index.
    assert (
        "ORDER BY c.embedding::halfvec(3072) <=> CAST(:emb AS halfvec(3072))"
        in sql
    )


@pytest.mark.asyncio
async def test_memories_fast_path_uses_halfvec_cast():
    db = _CaptureExecDb()
    repo = repository.RetrievalRepository(db)
    await repo.match_memories("e", 5, '{"chat_id": "c1"}')
    sql, _ = db.calls[0]
    sql_flat = " ".join(sql.split())
    assert "embedding::halfvec(3072) <=> CAST(:emb AS halfvec(3072))" in sql_flat
    assert "ORDER BY embedding::halfvec(3072) <=> CAST(:emb AS halfvec(3072))" in sql_flat


@pytest.mark.asyncio
async def test_active_project_ids_orders_deterministically():
    db = _ScalarsDb()
    repo = repository.RetrievalRepository(db)
    assert await repo.active_project_ids() == []
    assert "ORDER BY projects.id" in db.last_statement
