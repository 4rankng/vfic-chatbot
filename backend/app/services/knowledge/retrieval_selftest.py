"""Pre-activation retrieval self-test for category revisions.

Before a staged category revision becomes the project's active knowledge, this
module checks a bounded sample of records against their own declared query.
Each sampled record's most query-like field (``question`` → ``title`` →
``name``) is embedded and cosine-compared against that record's aligned unit
vector, with a per-field floor: 0.50 for recruiter-written questions, 0.45 for
title labels, 0.30 for place-name labels (the transportation bus routes, whose
short names measure systematically lower against long stops-and-notes records
— measured, not guessed; see ``RETRIEVAL_SELFTEST_NAME_FLOOR``). A different
record's high similarity cannot hide an unreachable answer. This is a
necessary sanity check, not proof of production ranking or factual
correctness; cross-project noise and retrieval policies still matter.

A failure indicates that a sampled query and its own answer are poorly aligned.
Activation fails with a dedicated code and offending queries in ``error_message``.

A query must be long enough to BE a retrieval signal. The exact rule: a query
with fewer than five letters (unicode alphabetic characters — punctuation does
not count toward the bound) is NOT testable by title alone and is SKIPPED,
never failed. Role acronyms like "QA", "SMT", "UI", "MV", "PCBA" or "LQC" are
the motivating case: at acronym length the embedding is noise (measured ~0.38
against its own record, below the floor, where ordinary titles start at 0.584),
so one acronym-titled row would otherwise kill an otherwise healthy category —
exactly the defect this skip exists to prevent. The gate stays strict for every
normal-length query: a record whose title genuinely disagrees with its content
still fails activation.

Cost: at most ``RETRIEVAL_SELFTEST_MAX_QUERIES`` extra embedding calls per
activation, bounded to the first records of the document.
"""

from __future__ import annotations

import math
from typing import Any, Protocol

from app.project_knowledge.domain.category_catalog import get_category_definition

# A record's query-vs-own-content similarity below this means the question and
# the answer content disagree semantically (the embedding model sees them as
# near-orthogonal). Calibrated on production lg-display FAQ chunks (n=52,
# OpenRouterEmbedder, 3072-dim): real question-vs-own-chunk similarity starts
# at 0.584 (p05 0.596, median 0.723), so 0.50 keeps a ~0.08 margin under real
# content while orthogonal embeddings (random topic drift) measure ~0.0-0.2.
# Recalibrate if the embedding model changes.
RETRIEVAL_SELFTEST_FLOOR = 0.50

# Title/name-fallback queries carry a lower floor. Production jobs briefs list
# whole role crews over ONE shared summary paragraph, so a short label's
# embedding against its own shared chunk sits systematically below a real
# question: AMTRAN's "Xưởng Nhựa" measured 0.47 against its own record —
# legitimately reachable, killed by the 0.50 question floor. Question-field
# queries keep the calibrated 0.50; label fallbacks get 0.45, which still
# rejects genuinely broken records (4P's mangled "KHO [MAT" measured 0.43).
RETRIEVAL_SELFTEST_TITLE_FLOOR = 0.45

# Name-fallback queries carry the lowest floor. Measured on the production
# LG-DISPLAY transportation catalog (2026-10-07, n=17 sampled legacy route
# names, first-25 window): every real, daily-running route label — "An
# Dương", "An Lão", "Hồ Sen", "Kiến Thụy", "Cầu Rào"... — embeds 0.33-0.45
# against its own stops-and-notes record, because a short place-name query is
# systematically weak against a long record. None of them is a broken record;
# they are the live bus catalog candidates ask about, and at the 0.45 title
# floor ANY update to the category fails activation over them. 0.30 still
# rejects near-orthogonal answers (random drift measures 0.0-0.2) while
# letting every measured real label through. Question stays 0.50; title stays
# 0.45.
RETRIEVAL_SELFTEST_NAME_FLOOR = 0.30

# Bound the extra embedding spend per activation. The first records are the
# ones recruiters wrote first; a gate over a bounded sample still catches a
# systematically broken document.
RETRIEVAL_SELFTEST_MAX_QUERIES = 25

# Most query-like field first. FAQ records answer a `question`; every other
# category falls back to the record's human-facing label.
_QUERY_FIELDS = ("question", "title", "name")

# Below this many letters (unicode alphabetic characters; punctuation does not
# count) a query carries too little lexical signal to embed as a retrieval
# signal — a role acronym like "QA", "SMT" or "PCBA" measures ~0.38 against its
# own record, below the floor — so it cannot be judged by title alone and is
# skipped rather than failed. See the module docstring.
_MIN_TESTABLE_QUERY_LETTERS = 5


class SelftestEmbedder(Protocol):
    async def batch(self, texts: list[str]) -> list[list[float]]: ...


class RetrievalSelftestError(RuntimeError):
    """The revision's own records cannot be retrieved by their declared queries."""

    def __init__(self, failures: list[str]) -> None:
        super().__init__("; ".join(failures))
        self.failures = failures


def _selftest_query(payload: dict[str, Any]) -> tuple[str, str] | None:
    """The record's most query-like field and the field name that supplied it.

    The field name decides the floor: a recruiter-written `question` is a real
    retrieval query, while a `title`/`name` fallback is a short label whose
    embedding over a shared summary sits systematically lower.
    """
    for field in _QUERY_FIELDS:
        value = payload.get(field)
        if isinstance(value, str) and value.strip():
            return value.strip(), field
    return None


def _query_is_testable(query: str) -> bool:
    """Whether the query is long enough to be judged by this gate.

    False for acronym-length labels (fewer than ``_MIN_TESTABLE_QUERY_LETTERS``
    letters) like "QA", "SMT", "UI", "MV", "PCBA" or "LQC": at that length the
    title-only embedding is noise and cannot retrieve the record's own content
    either way, so the record is not testable by title alone. It is still
    activated — being untestable is not a defect — but it never fails (or even
    spends an embedding call on) the gate. Everything with five or more letters
    is tested at full strictness.
    """
    return sum(1 for ch in query if ch.isalpha()) >= _MIN_TESTABLE_QUERY_LETTERS


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
    skipped, as are queries too short to be a retrieval signal
    (``_query_is_testable`` — role acronyms like "QA" cannot self-retrieve by
    title alone and must not fail activation for it); a document where nothing
    is testable passes.
    """
    if len(units) != len(vectors) or not units:
        return []
    definition_field = _record_list_field(document)
    if definition_field is None:
        return []
    records = getattr(document, definition_field)[:RETRIEVAL_SELFTEST_MAX_QUERIES]
    queries: list[str] = []
    query_fields: list[str] = []
    record_vectors: list[list[float]] = []
    for index, record in enumerate(records):
        payload = record.model_dump(mode="json", exclude_none=True)
        query_field = _selftest_query(payload)
        if query_field is not None and _query_is_testable(query_field[0]):
            query, field = query_field
            queries.append(query)
            query_fields.append(field)
            record_vectors.append(vectors[index])
    if not queries:
        return []
    query_vectors = await embedder.batch(queries)
    failures: list[str] = []
    for query, field, query_vector, record_vector in zip(
        queries, query_fields, query_vectors, record_vectors, strict=True
    ):
        floor = (
            RETRIEVAL_SELFTEST_FLOOR
            if field == "question"
            else RETRIEVAL_SELFTEST_TITLE_FLOOR
            if field == "title"
            else RETRIEVAL_SELFTEST_NAME_FLOOR
        )
        similarity = _cosine(query_vector, record_vector)
        if not math.isfinite(similarity) or similarity < floor:
            failures.append(
                f'"{query}" would not retrieve its own record '
                f"(own-record similarity {similarity:.2f} < {floor:.2f})"
            )
    return failures


def _record_list_field(document: Any) -> str | None:
    """The document's record-list attribute name, mirroring the category definition."""
    definition = getattr(document, "category", None)
    if definition is None:
        return None
    try:
        return get_category_definition(definition).list_field
    except (KeyError, ValueError):
        return None
