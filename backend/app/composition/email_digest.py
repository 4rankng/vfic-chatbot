"""Composition root for the candidate email digest's LLM wiring.

The digest needs a summarizer in BOTH transports — the RQ worker's hourly tick
and the FastAPI console preview route — but neither may reach the graph layer
directly: services must not import ``app.graph``, and an ``api → app.graph``
edge would be a new architecture-boundary exception. This module is the single
seam both call, so the concrete provider chain stays owned by
``app.graph.factories`` and neither transport grows a backedge.
"""

from __future__ import annotations


async def build_digest_summarizer_for(db):
    """The digest summarizer bound to the operator's provider failover chain.

    ``app.graph.factories`` is imported inside the function so the web process
    stays langchain-free at import time, matching the lazy-SDK convention the
    graph package uses elsewhere.

    Raises when every enabled provider fails to build — the worker treats that
    as a failed tick, while the preview route degrades to no summarizer rather
    than failing an explicit operator action.
    """
    from app.graph.factories import build_digest_summarizer

    return await build_digest_summarizer(db)


__all__ = ["build_digest_summarizer_for"]