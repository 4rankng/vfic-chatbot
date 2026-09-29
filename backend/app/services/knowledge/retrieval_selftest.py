"""Pre-activation retrieval self-test for category revisions.

Before a staged category revision becomes the project's active knowledge, this
module answers one question with the revision's own content: **can each record
be retrieved by the query its own fields declare?** Every record is reduced to
its most query-like field (``question`` → ``title`` → ``name``), embedded, and
cosine-compared against ALL of the revision's unit vectors — the same ranking
job the production vector search will do against these chunks, minus noise from
other projects (a pass here is necessary, not sufficient; whole-KB noise only
lowers similarity further).

A failure means the content cannot serve candidates as written: the question a
recruiter typed would not surface this record. That is the same class of
blocking defect as an invalid payload, so activation fails with a dedicated
code and the offending queries in ``error_message``.

Cost: at most ``RETRIEVAL_SELFTEST_MAX_QUERIES`` extra embedding calls per
activation, bounded to the first records of the document.
"""

from __future__ import annotations

import math
from typing import Any, Protocol

# A record's query-vs-own-content similarity below this means the question and
# the answer content disagree semantically (the embedding model sees them as
# near-orthogonal). Calibrated on production lg-display FAQ chunks (n=52,
# OpenRouterEmbedder, 3072-dim): real question-vs-own-chunk similarity starts
# at 0.584 (p05 0.596, median 0.723), so 0.50 keeps a ~0.08 margin under real
# content while orthogonal embeddings (random topic drift) measure ~0.0-0.2.
# Recalibrate if the embedding model changes.
RETRIEVAL_SELFTEST_FLOOR = 0.50

# Bound the extra embedding spend per activation. The first records are the
# ones recruiters wrote first; a gate over a bounded sample still catches a
# systematically broken document.
RETRIEVAL_SELFTEST_MAX_QUERIES = 25

# Most query-like field first. FAQ records answer a `question`; every other
# category falls back to the record's human-facing label.
_QUERY_FIELDS = ("question", "title", "name")


class SelftestEmbedder(Protocol):
    async def batch(self, texts: list[str]) -> list[list[float]]: ...


class RetrievalSelftestError(RuntimeError):
    """The revision's own records cannot be retrieved by their declared queries."""

    def __init__(self, failures: list[str]) -> None:
        super().__init__("; ".join(failures))
        self.failures = failures


def _selftest_query(payload: dict[str, Any]) -> str | None:
    for field in _QUERY_FIELDS:
        value = payload.get(field)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _cosine(a: list[float], b: list[float]) -> float:
    dot = 0.0
    na = 0.0
    nb = 0.0
    for x, y in zip(a, b, strict=True):
        dot += x * y
        na += x * x
        nb += y * y
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / math.sqrt(na * nb)


async def retrieval_selftest_failures(
    document: Any,
    units: list[dict],
    vectors: list[list[float]],
    embedder: SelftestEmbedder,
) -> list[str]:
    """Return human-readable failures; empty list means the gate passes.

    ``document`` is the validated category document and ``units``/``vectors``
    are exactly what ``render_category_units`` produced and the embedder
    returned for it — index-aligned. Records without a query-like field are
    skipped; a document where nothing is testable passes.
    """
    if len(units) != len(vectors) or not units:
        return []
    definition_field = _record_list_field(document)
    if definition_field is None:
        return []
    records = getattr(document, definition_field)[:RETRIEVAL_SELFTEST_MAX_QUERIES]
    queries: list[str] = []
    for record in records:
        payload = record.model_dump(mode="json", exclude_none=True)
        query = _selftest_query(payload)
        if query is not None:
            queries.append(query)
    if not queries:
        return []
    query_vectors = await embedder.batch(queries)
    failures: list[str] = []
    floor_text = f"{RETRIEVAL_SELFTEST_FLOOR:.2f}"
    for query, query_vector in zip(queries, query_vectors, strict=True):
        best = max(_cosine(query_vector, vector) for vector in vectors)
        if best < RETRIEVAL_SELFTEST_FLOOR:
            failures.append(
                f'"{query}" would not retrieve its own record '
                f"(best similarity {best:.2f} < {floor_text})"
            )
    return failures


def _record_list_field(document: Any) -> str | None:
    """The document's record-list attribute name, mirroring the category definition."""
    definition = getattr(document, "category", None)
    if definition is None:
        return None
    from app.services.knowledge.category_projections import get_category_definition

    try:
        return get_category_definition(definition).list_field
    except (KeyError, ValueError):
        return None
