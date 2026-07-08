"""Characterization of the ANN-enable gate in RetrievalRepository.

ANN retrieval uses a pgvector halfvec(EMBEDDING_DIM) HNSW index, so it is only
safe when the configured embedding dimension matches the schema. The gate must
disable ANN (and warn, once) on a mismatch instead of silently querying a
wrong-width index. These pin that behavior so a future change can't quietly
re-introduce the bare ``== 3072`` literal or drop the mismatch signal.
"""
from __future__ import annotations

import logging
from types import SimpleNamespace

from app.services.retrieval import repository


def _settings(*, rag_ann_enabled: bool, embedding_dim: int) -> SimpleNamespace:
    return SimpleNamespace(rag_ann_enabled=rag_ann_enabled, embedding_dim=embedding_dim)


def test_ann_enabled_when_flag_on_and_dim_matches_schema(monkeypatch):
    monkeypatch.setattr(
        repository,
        "get_settings",
        lambda: _settings(rag_ann_enabled=True, embedding_dim=repository.EMBEDDING_DIM),
    )
    assert repository.RetrievalRepository._ann_enabled() is True


def test_ann_disabled_and_warns_once_on_dim_mismatch(monkeypatch, caplog):
    monkeypatch.setattr(repository, "_ann_dim_mismatch_warned", False)
    monkeypatch.setattr(
        repository,
        "get_settings",
        lambda: _settings(rag_ann_enabled=True, embedding_dim=1536),
    )

    with caplog.at_level(logging.WARNING, logger=repository.logger.name):
        assert repository.RetrievalRepository._ann_enabled() is False
    assert any("ANN retrieval disabled" in r.message for r in caplog.records)

    # The guard is one-shot: a second call must not re-warn.
    caplog.clear()
    with caplog.at_level(logging.WARNING, logger=repository.logger.name):
        assert repository.RetrievalRepository._ann_enabled() is False
    assert not any("ANN retrieval disabled" in r.message for r in caplog.records)


def test_ann_disabled_when_flag_off_regardless_of_dim(monkeypatch, caplog):
    monkeypatch.setattr(repository, "_ann_dim_mismatch_warned", False)
    monkeypatch.setattr(
        repository,
        "get_settings",
        lambda: _settings(rag_ann_enabled=False, embedding_dim=1536),
    )
    with caplog.at_level(logging.WARNING, logger=repository.logger.name):
        assert repository.RetrievalRepository._ann_enabled() is False
    assert not any("ANN retrieval disabled" in r.message for r in caplog.records)
