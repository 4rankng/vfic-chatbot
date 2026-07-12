"""Shared pgvector literal formatting.

Used by every service/tool that hands an embedding to a `CAST(:emb AS vector)`
query, so the wire format (precision, brackets, empty-handling) is defined once
instead of copy-pasted across modules where it had already started to drift.
"""

from __future__ import annotations


def vec_literal(v: list[float] | None) -> str:
    """Format an embedding as a pgvector string literal.

    Returns ``""`` for falsy input so callers that pre-validate non-empty
    embeddings are unaffected; an empty embedding is a caller bug regardless.
    """
    if not v:
        return ""
    return "[" + ",".join(f"{x:.8f}" for x in v) + "]"
