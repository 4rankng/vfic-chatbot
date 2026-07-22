"""Grounding enforcement: prevents the agent from citing job_ids it was never shown.

All three research docs flag this gap: citations exist in tool context but nothing
validates the final reply actually references retrieved data. This module provides
pure functions to close that loop:

* ``extract_surfaced_job_ids`` — pull job IDs from tool-result text (what the LLM saw).
* ``extract_cited_job_ids`` — pull job IDs from the reply (what the LLM claimed).
* ``validate_grounding`` — diff the two, return hallucinated IDs + a sanitized reply.
* ``extract_surfaced_entities`` — pull company/factory/project names from the
  structured tool payloads (the authoritative entity set the reply may reference).
* ``validate_entity_grounding`` — flag property assertions in the reply about
  entities the evidence never surfaced (e.g. "Rorze không có KTX" when no tool
  returned data for Rorze). Sanitize-only: appends a hedging footer, never rewrites.

Intentionally pure (no DB, no LLM) so :mod:`backend.tests.test_grounding` can pin
every branch in isolation. The wiring into the agent loop is in :mod:`clients`.
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass, field

# Job IDs surface in tool results as "id=uuid" (from recommend_jobs) or bare UUIDs.
# We match both the tagged form and standalone UUIDs to catch loose citations.
_JOB_ID_TAG_RE = re.compile(
    r"id=([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})", re.IGNORECASE
)
_BARE_UUID_RE = re.compile(
    r"\b([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})\b", re.IGNORECASE
)

# Structured tool payloads the agent surfaces. Entity names are pulled from these
# (not from free-text KB chunks) so the authoritative set matches exactly what the
# tools returned. Kept in sync with app/graph/tools.py rendering.
_ACTIVE_JOB_LOOKUP_PREFIX = "ACTIVE_JOB_LOOKUP_JSON="
_PRODUCT_FEATURES_HEADER_RE = re.compile(
    r"Đặc điểm sản phẩm\s*—\s*dự án\s*'([^']+)'\s*:", re.IGNORECASE
)
# Job-listing JSON carries these per-row keys (see _active_job_payload in tools.py).
_ENTITY_JSON_KEYS = ("company", "factory", "project")


def _extract_ids(text: str, pattern: re.Pattern[str]) -> set[str]:
    return {m.lower() for m in pattern.findall(text or "")}


def extract_surfaced_job_ids(tool_results: list[str]) -> set[str]:
    """All job IDs the LLM was shown via tool results during the turn."""
    surfaced: set[str] = set()
    for result in tool_results or []:
        surfaced |= _extract_ids(result, _JOB_ID_TAG_RE)
        surfaced |= _extract_ids(result, _BARE_UUID_RE)
    return surfaced


def extract_cited_job_ids(reply: str) -> set[str]:
    """All job IDs the reply text references (tagged or bare UUID)."""
    text = reply or ""
    return _extract_ids(text, _JOB_ID_TAG_RE) | _extract_ids(text, _BARE_UUID_RE)


@dataclass(frozen=True)
class GroundingResult:
    """Outcome of the grounding cross-check."""

    is_grounded: bool
    hallucinated_ids: frozenset[str]
    sanitized_reply: str
    reason: str = ""
    unsupported_entities: frozenset[str] = field(default_factory=frozenset)


def validate_grounding(
    reply: str,
    surfaced_ids: set[str],
    surfaced_entities: set[str] | None = None,
) -> GroundingResult:
    """Cross-check cited job IDs and entity claims against retrieved evidence.

    Job-ID path: on hallucination (a cited ID not in the surfaced set), the
    offending IDs are stripped from the reply. The reply is never fully replaced —
    the agent may still have useful non-citation content. If the reply is *entirely*
    about a hallucinated job (no grounded content remains after stripping), the
    caller should swap to an abstain reply.

    Entity path: property assertions about entities absent from ``surfaced_entities``
    (e.g. "Rorze không có KTX" when no tool returned Rorze data) get a hedging
    footer appended. Sanitize-only — the reply body is preserved.

    An empty ``surfaced_ids`` set means no job data was retrieved this turn; any
    job_id citation is then suspect, but we don't false-positive on an empty reply.
    An empty/None ``surfaced_entities`` skips the entity check (no structured
    evidence to diff against — the agent-layer abstain path handles that case).
    """
    cited = extract_cited_job_ids(reply)
    sanitized = reply
    hallucinated: set[str] = set()
    reason = ""
    if cited:
        hallucinated = cited - surfaced_ids if surfaced_ids else cited
        if hallucinated:
            # Strip hallucinated IDs. Case-insensitive: UUIDs are valid in either
            # case, and a safety guardrail must survive an LLM uppercasing one.
            for hid in hallucinated:
                sanitized = re.sub(
                    re.escape(f"id={hid}"),
                    "[việc không xác định]",
                    sanitized,
                    flags=re.IGNORECASE,
                )
                sanitized = re.sub(re.escape(hid), "", sanitized, flags=re.IGNORECASE)
            reason = "cited_job_id_not_in_retrieved_set"

    # Entity cross-check runs after ID sanitization so the footer appends to the
    # already-cleaned text. Returns no-ops when there is nothing to flag.
    unsupported: frozenset[str] = frozenset()
    if surfaced_entities:
        unsupported, sanitized = validate_entity_grounding(sanitized, surfaced_entities)
        if unsupported and not reason:
            reason = "unsupported_entity_claim"

    if not hallucinated and not unsupported:
        return GroundingResult(
            is_grounded=True,
            hallucinated_ids=frozenset(),
            sanitized_reply=reply,
            unsupported_entities=frozenset(),
        )

    return GroundingResult(
        is_grounded=False,
        hallucinated_ids=frozenset(hallucinated),
        sanitized_reply=sanitized.strip(),
        reason=reason,
        unsupported_entities=frozenset(unsupported),
    )


def _extract_entities_from_json_payload(first_line: str) -> set[str]:
    """Pull company/factory/project names from one ``ACTIVE_JOB_LOOKUP_JSON=`` row."""
    entities: set[str] = set()
    try:
        payload = json.loads(first_line.removeprefix(_ACTIVE_JOB_LOOKUP_PREFIX))
    except (TypeError, ValueError):
        return entities
    if not isinstance(payload, dict):
        return entities
    jobs = payload.get("jobs")
    if not isinstance(jobs, list):
        return entities
    for job in jobs:
        if not isinstance(job, dict):
            continue
        for key in _ENTITY_JSON_KEYS:
            value = job.get(key)
            if isinstance(value, str) and value.strip():
                entities.add(value.strip())
    return entities


def extract_surfaced_entities(tool_results: list[str]) -> set[str]:
    """Company/factory/project names the LLM was shown via structured tool results.

    Reads only the authoritative structured payloads (``list_active_jobs`` JSON and
    ``get_product_features`` headers) — not free-text KB chunks, which can mention a
    factory in passing without establishing an authoritative record. The reply may
    assert properties only about entities in this set.
    """
    entities: set[str] = set()
    for result in tool_results or []:
        text = str(result or "")
        first_line = text.partition("\n")[0]
        if first_line.startswith(_ACTIVE_JOB_LOOKUP_PREFIX):
            entities |= _extract_entities_from_json_payload(first_line)
        for match in _PRODUCT_FEATURES_HEADER_RE.finditer(text):
            entities.add(match.group(1).strip())
    return entities


# A property assertion is a sentence that (a) names an entity and (b) attaches a
# factual claim about it. We detect the claim via Vietnamese affirmative/negative
# copular phrasings so the check is language-shaped, not a hardcoded entity list.
# Matches: "LG Display có KTX", "Rorze không có KTX", "Samsung có hỗ trợ chỗ ở".
_PROPERTY_ASSERTION_RE = re.compile(
    r"(?P<entity>[^\n,.:;]{2,60}?)\s+(?P<predicate>(?:không\s+|chưa\s+|chưa\s+có\s+)?"
    r"(?:có|có\s+hỗ\s+trợ|đang\s+có))\s+",
    re.IGNORECASE,
)
# Generic lead-ins that are not entity names (Vietnamese pronouns / discourse).
_ASSERTION_STOPWORDS = frozenset(
    {
        "bạn",
        "tôi",
        "chúng",
        "mình",
        "công ty",
        "nha may",  # "nhà máy" normalized for matching
        "du an",  # "dự án"
        "vi tri",  # "vị trí"
    }
)


def _normalize_entity(text: str) -> str:
    """ASCII-fold + lowercase so "LG Display" matches "lg display"."""
    normalized = unicodedata.normalize("NFKD", text or "")
    ascii_text = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    return ascii_text.replace("đ", "d").replace("Đ", "D").lower().strip()


def extract_asserted_entities(reply: str) -> set[str]:
    """Entities the reply makes a property assertion about.

    Returns the entity substrings (normalized) that appear as the subject of a
    ``có``/``có hỗ trợ``/``không có`` predicate. Used to diff against the surfaced
    entity set. Pronouns and generic nouns are excluded so "bạn có muốn..." does
    not fire.
    """
    asserted: set[str] = set()
    for match in _PROPERTY_ASSERTION_RE.finditer(reply or ""):
        entity = _normalize_entity(match.group("entity"))
        # Drop trailing pronouns/discourse glued to a real entity, e.g.
        # "còn Rorze" → "rorze". Keep the final token run that isn't a stopword.
        tokens = [t for t in re.split(r"\s+", entity) if t]
        while tokens and tokens[-1] in _ASSERTION_STOPWORDS:
            tokens.pop()
        while tokens and tokens[0] in _ASSERTION_STOPWORDS:
            tokens.pop(0)
        candidate = " ".join(tokens).strip(" ,.;:-")
        if len(candidate) < 3 or candidate in _ASSERTION_STOPWORDS:
            continue
        asserted.add(candidate)
    return asserted


def _normalize_entity_set(entities: set[str]) -> set[str]:
    return {_normalize_entity(e) for e in entities}


def validate_entity_grounding(
    reply: str, surfaced_entities: set[str]
) -> tuple[frozenset[str], str]:
    """Flag property assertions about entities the evidence never surfaced.

    Returns ``(unsupported, sanitized_reply)``. Sanitize-only: a short hedging
    footer is appended listing the unverified entities; the reply body is never
    rewritten (the pending Phase 3 plan explicitly rejected brittle rewrites).

    Returns an empty set (and the reply unchanged) when every asserted entity was
    surfaced, or when no structured entity evidence was provided at all (in which
    case we cannot distinguish a hallucination from a legitimate KB-chunk mention,
    so we do not false-positive — the abstain path in the agent layer handles the
    no-evidence case).
    """
    if not surfaced_entities:
        return frozenset(), reply
    asserted = extract_asserted_entities(reply)
    if not asserted:
        return frozenset(), reply
    surfaced_norm = _normalize_entity_set(surfaced_entities)
    unsupported = frozenset(
        entity for entity in asserted if entity not in surfaced_norm
    )
    if not unsupported:
        return frozenset(), reply
    names = ", ".join(sorted(unsupported))
    footer = f"\n\n(thông tin về {names} chưa được xác minh từ dữ liệu tra cứu)"
    return unsupported, (reply.rstrip() + footer)
