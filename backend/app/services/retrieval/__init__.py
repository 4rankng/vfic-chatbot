"""Retrieval data-access package for the agent layer.

Re-exports ``RetrievalRepository``, which concentrates the read-only SQL the graph
tools (``app/graph/tools.py``) and prompt assembly (``app/graph/context.py``) need,
so the graph layer contains no ``text()`` SQL.
"""
from app.services.retrieval.repository import RetrievalRepository

__all__ = ["RetrievalRepository"]
