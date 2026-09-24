"""Retrieval data-access package for the agent layer.

Re-exports ``RetrievalRepository``, the facade that binds one db session (plus
the optional multi-Page project scope) to the document, FAQ, catalog, and
timetable repositories owning the read-only SQL the graph tools
(``app/graph/tools.py``) and prompt assembly (``app/graph/context.py``) need,
so the graph layer contains no ``text()`` SQL.
"""

from app.services.retrieval.repository import RetrievalRepository

__all__ = ["RetrievalRepository"]
