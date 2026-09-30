"""Shared embedding wire formats.

Two formats live here, both defined once for the same reason: every module that
handles an embedding vector must agree byte-for-byte, or a cache written by one
module silently misses in another.

  * :func:`vec_literal` — the pgvector text format for ``CAST(:emb AS vector)``.
  * :func:`pack_vector` / :func:`unpack_vector` — the packed base64 float16
    format for vectors stored in Redis (the embed cache and the semantic cache
    both use it).
"""

from __future__ import annotations

import base64
import struct


def vec_literal(v: list[float] | None) -> str:
    """Format an embedding as a pgvector string literal.

    Returns ``""`` for falsy input so callers that pre-validate non-empty
    embeddings are unaffected; an empty embedding is a caller bug regardless.
    """
    if not v:
        return ""
    return "[" + ",".join(f"{x:.8f}" for x in v) + "]"


def pack_vector(vector: list[float]) -> str:
    """Pack an embedding as base64 float16 (~2 bytes/dim vs ~20 as a JSON array)."""
    return base64.b64encode(struct.pack(f"<{len(vector)}e", *vector)).decode("ascii")


def unpack_vector(payload: object) -> list[float] | None:
    """Inverse of :func:`pack_vector`.

    Returns None on any non-packed payload: legacy JSON-array entries written
    before the packed format simply miss and repopulate on the next embed.
    """
    if not isinstance(payload, str) or not payload:
        return None
    try:
        blob = base64.b64decode(payload, validate=True)
        return list(struct.unpack(f"<{len(blob) // 2}e", blob))
    except Exception:  # noqa: BLE001 — corrupt/legacy values are a cache miss
        return None
