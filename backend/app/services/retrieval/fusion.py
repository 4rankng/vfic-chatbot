"""Deterministic rank fusion for independent retrieval signals."""
from __future__ import annotations

from collections.abc import Iterable


def reciprocal_rank_fuse(
    vector_rows: Iterable[object],
    lexical_rows: Iterable[object],
    *,
    top_k: int,
    rank_constant: int = 60,
) -> list[object]:
    """Fuse ranked vector and lexical evidence with reciprocal-rank fusion.

    Scores within either retriever are not comparable, so only each row's rank
    contributes. Ties retain a deterministic first-seen order and malformed rows
    without an id are ignored rather than becoming uncitable agent context.
    """
    if top_k <= 0:
        return []

    scores: dict[str, float] = {}
    rows: dict[str, object] = {}
    first_seen: dict[str, int] = {}
    sequence = 0
    for ranked_rows in (vector_rows, lexical_rows):
        for rank, row in enumerate(ranked_rows, start=1):
            row_id = getattr(row, "id", None)
            if row_id is None:
                continue
            key = str(row_id)
            scores[key] = scores.get(key, 0.0) + 1.0 / (rank_constant + rank)
            rows.setdefault(key, row)
            first_seen.setdefault(key, sequence)
            sequence += 1

    ranked_ids = sorted(
        rows,
        key=lambda key: (-scores[key], first_seen[key], key),
    )
    return [rows[key] for key in ranked_ids[:top_k]]
