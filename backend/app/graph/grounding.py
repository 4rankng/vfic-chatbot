"""Grounding enforcement: prevents the agent from citing job_ids it was never shown.

All three research docs flag this gap: citations exist in tool context but nothing
validates the final reply actually references retrieved data. This module provides
pure functions to close that loop:

* ``extract_surfaced_ids`` — pull IDs from tool-result text (what the LLM saw).
* ``extract_cited_ids`` — pull IDs from the reply (what the LLM claimed).
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
import logging
import re
import unicodedata
from dataclasses import dataclass, field
from typing import NamedTuple

logger = logging.getLogger(__name__)

# Project IDs surface in tool results as "id=uuid" (from list_active_projects) or bare
# UUIDs. We match both the tagged form and standalone UUIDs to catch loose citations.
_JOB_ID_TAG_RE = re.compile(
    r"id=([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})", re.IGNORECASE
)
_BARE_UUID_RE = re.compile(
    r"\b([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})\b", re.IGNORECASE
)

# Structured tool payloads the agent surfaces. Entity names are pulled from these
# (not from free-text KB chunks) so the authoritative set matches exactly what the
# tools returned. Kept in sync with app/graph/tools/catalog.py rendering.
_ACTIVE_PROJECT_LOOKUP_PREFIX = "ACTIVE_PROJECT_LOOKUP_JSON="
# Statuses the project lookup tool actually emits (``no_match`` is no longer a
# status: a criteria miss is a ``matched`` empty list with honest notes).
_ACTIVE_PROJECT_LOOKUP_STATUSES = frozenset({"matched", "catalog_empty", "unavailable"})
_PRODUCT_FEATURES_HEADER_RE = re.compile(
    r"Đặc điểm sản phẩm\s*—\s*dự án\s*'([^']+)'\s*:", re.IGNORECASE
)
# Project-listing JSON carries these per-row keys (see _project_payload in tools/catalog.py).
_ENTITY_JSON_KEYS = ("company", "factory", "project")


def _extract_ids(text: str, pattern: re.Pattern[str]) -> set[str]:
    return {m.lower() for m in pattern.findall(text or "")}


def extract_surfaced_ids(tool_results: list[str]) -> set[str]:
    """All IDs the LLM was shown via tool results during the turn."""
    surfaced: set[str] = set()
    for result in tool_results or []:
        surfaced |= _extract_ids(result, _JOB_ID_TAG_RE)
        surfaced |= _extract_ids(result, _BARE_UUID_RE)
    return surfaced


def extract_cited_ids(reply: str) -> set[str]:
    """All IDs the reply text references (tagged or bare UUID)."""
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
    footer appended. Sanitize-only — the reply body is preserved. On a no_match
    turn, ``surfaced_entities`` is populated from ``alternative_jobs``, so an
    invented company on an abstention reply (e.g. "LG đang tuyển 30 triệu" when
    only Samsung was returned as an alternative) is hedged the same way.

    An empty ``surfaced_ids`` set means no job data was retrieved this turn; any
    job_id citation is then suspect, but we don't false-positive on an empty reply.
    An empty/None ``surfaced_entities`` skips the entity check (no structured
    evidence to diff against — the agent-layer abstain path handles that case).
    """
    cited = extract_cited_ids(reply)
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
    """Pull company/factory/project names from one ``ACTIVE_PROJECT_LOOKUP_JSON=`` row.

    Reads the ``projects`` list (the ranked project catalog the model composes
    from). Surfacing the whole catalog structurally keeps entity grounding
    aligned with what was actually returned — the model may only name
    companies/factories from these rows — without a second LLM call.
    """
    entities: set[str] = set()
    try:
        payload = json.loads(first_line.removeprefix(_ACTIVE_PROJECT_LOOKUP_PREFIX))
    except (TypeError, ValueError):
        return entities
    if not isinstance(payload, dict):
        return entities
    project_lists = []
    value = payload.get("projects")
    if isinstance(value, list):
        project_lists.append(value)
    for projects in project_lists:
        for project in projects:
            if not isinstance(project, dict):
                continue
            for key in _ENTITY_JSON_KEYS:
                value = project.get(key)
                if isinstance(value, str) and value.strip():
                    entities.add(value.strip())
    return entities


def extract_surfaced_entities(tool_results: list[str]) -> set[str]:
    """Company/factory/project names the LLM was shown via structured tool results.

    Reads only the authoritative structured payloads (``list_active_projects`` JSON and
    ``get_product_features`` headers) — not free-text KB chunks, which can mention a
    factory in passing without establishing an authoritative record. The reply may
    assert properties only about entities in this set.
    """
    entities: set[str] = set()
    for result in tool_results or []:
        text = str(result or "")
        first_line = text.partition("\n")[0]
        if first_line.startswith(_ACTIVE_PROJECT_LOOKUP_PREFIX):
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
# ASCII-folded at module load so comparison is consistent with ``_normalize_entity``
# (which lowercases + strips diacritics). Storing "bạn" here would never match the
# normalized "ban" the regex produces.
def _fold(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text)
    ascii_text = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    return ascii_text.replace("đ", "d").replace("Đ", "D").lower().strip()


_ASSERTION_STOPWORDS = frozenset(
    _fold(s)
    for s in (
        "bạn",
        "tôi",
        "chúng",
        "mình",
        "công ty",
        "nhà máy",
        "dự án",
        "vị trí",
        "công ty chúng tôi",
        # Discourse adverbs/connectors that precede or wrap a predicate without
        # being an entity subject ("Hiện chưa có...", "còn Samsung thì có...",
        # "Công ty chúng tôi có..."). These are not factory/company names, so
        # asserting them as entities would false-positive on legitimate abstention
        # replies or break slug/display-name token matching.
        "hiện",
        "hiện tại",
        "hiện nay",
        "nay",
        "đây",
        "đó",
        "vẫn",
        "đang",
        "còn",
        "thì",
        "là",
        "với",
        "cả",
        "nhưng",
        "mà",
        "của",
        "riêng",
        "như",
    )
)


def _normalize_entity(text: str) -> str:
    """ASCII-fold + lowercase so "LG Display" matches "lg display"."""
    return _fold(text or "")


def _strip_stopword_edges(tokens: list[str]) -> list[str]:
    """Remove leading/trailing stopwords and stopword phrases.

    Handles multi-word discourse phrases like "hiện tại" so an entity captured as
    ``["hien", "tai"]`` is fully stripped (both tokens are stopwords together),
    while a real entity like ``["lg", "display"]`` is preserved. Iterates until no
    edge changes so ``["hien", "tai", "con", "rorze"]`` → ``["rorze"]``.
    """
    while tokens:
        changed = False
        # Try the longest leading stopword phrase first.
        for length in range(min(len(tokens), 3), 0, -1):
            phrase = " ".join(tokens[:length])
            if phrase in _ASSERTION_STOPWORDS:
                tokens = tokens[length:]
                changed = True
                break
        if not changed:
            break
    while tokens:
        changed = False
        for length in range(min(len(tokens), 3), 0, -1):
            phrase = " ".join(tokens[-length:])
            if phrase in _ASSERTION_STOPWORDS:
                tokens = tokens[:-length]
                changed = True
                break
        if not changed:
            break
    return tokens


def extract_asserted_entities(reply: str) -> set[str]:
    """Entities the reply makes a property assertion about.

    Returns the entity substrings (normalized) that appear as the subject of a
    ``có``/``có hỗ trợ``/``không có`` predicate. Used to diff against the surfaced
    entity set. Pronouns, generic nouns, and discourse adverbs are excluded so
    "bạn có muốn...", "công ty có...", and "hiện tại chưa có..." do not fire.
    """
    asserted: set[str] = set()
    for match in _PROPERTY_ASSERTION_RE.finditer(reply or ""):
        entity = _normalize_entity(match.group("entity"))
        tokens = [t for t in re.split(r"\s+", entity) if t]
        tokens = _strip_stopword_edges(tokens)
        candidate = " ".join(tokens).strip(" ,.;:-")
        if len(candidate) < 3 or candidate in _ASSERTION_STOPWORDS:
            continue
        asserted.add(candidate)
    return asserted


def _canonical_entity(entity: str) -> str:
    """Normalize display names and slugs to one exact comparison form."""
    return " ".join(re.findall(r"[a-z0-9]+", _normalize_entity(entity)))


def validate_entity_grounding(
    reply: str, surfaced_entities: set[str]
) -> tuple[frozenset[str], str]:
    """Flag property assertions about entities the evidence never surfaced.

    Returns ``(unsupported, reply)``. Detection-only: the unsupported set drives
    the decision trace and the grounding metric, but the reply is handed back
    untouched. The previous hedging footer showed candidates internal retrieval
    bookkeeping — it fired on the operator's own brand name and read as the bot
    doubting itself mid-conversation.

    Returns an empty set (and the reply unchanged) when every asserted entity was
    surfaced, or when no structured entity evidence was provided at all (in which
    case we cannot distinguish a hallucination from a legitimate KB-chunk mention,
    so we do not false-positive — the abstain path in the agent layer handles the
    no-evidence case).

    Matching is exact after separator/diacritic normalization, so a slug
    (``lg-display``) and display name (``LG Display``) confirm each other without
    letting related but distinct projects (``samsung-bac-ninh`` and
    ``Samsung Bắc Giang``) validate one another.
    """
    if not surfaced_entities:
        return frozenset(), reply
    asserted = extract_asserted_entities(reply)
    if not asserted:
        return frozenset(), reply
    surfaced_canonical = {_canonical_entity(entity) for entity in surfaced_entities}
    unsupported = frozenset(
        entity for entity in asserted if _canonical_entity(entity) not in surfaced_canonical
    )
    return unsupported, reply


# ── Contact-channel grounding ───────────────────────────────────────────────
# A wrong phone number costs more than a missing one: a candidate who calls an
# invented hotline is worse served than one who reads "chưa có thông tin". The
# prompt forbids inventing contact channels; this is the deterministic backstop
# for the observed failure where an off-scope refusal fabricated an "internal IT
# hotline" and an IT e-mail that no source ever contained.
# Separator runs are allowed between digit groups — "(0251) 543-6789" is one
# number, and a single separator slot would stop the match at "(0251)".
_PHONE_CANDIDATE_RE = re.compile(
    r"(?<![\d])(?:\+?84|0)(?:[\s.\-()]{0,3}\d){8,11}(?!\d)"
)
_EMAIL_CANDIDATE_RE = re.compile(r"(?<![\w.\-])[\w.\-+]+@[\w\-]+(?:\.[\w\-]+)+")
class _UngroundedContact(NamedTuple):
    """Signal that the reply stated a contact channel the evidence never had.

    Replaces the former canned ``UNVERIFIED_CONTACT_REPLY``: the guard still
    refuses to ship an invented hotline, but the caller repairs by asking the
    model to rewrite rather than substituting code-authored prose. A second
    violation suppresses the turn (empty reply) instead of re-running.
    """

    channels: tuple[str, ...]


# ── Lane-unavailable replies ─────────────────────────────────────────────────
# There is deliberately no code-authored "unavailable" line any more: a turn
# that cannot compose an answer gets one final tool-free generation round
# (``clients.MiniMaxAgent._compose_with_instruction``) and suppresses on empty,
# so no constant here can ever be shipped to a candidate.


def _normalize_phone(raw: str) -> str:
    """Digits only, with the ``+84`` country code folded onto the local ``0``."""
    digits = re.sub(r"\D", "", raw or "")
    if digits.startswith("84") and len(digits) > 9:
        digits = "0" + digits[2:]
    return digits


def extract_contact_channels(text: str) -> frozenset[str]:
    """Phone numbers (normalized to digits) and lowercased e-mail addresses."""
    channels: set[str] = set()
    for match in _PHONE_CANDIDATE_RE.finditer(text or ""):
        digits = _normalize_phone(match.group(0))
        if len(digits) >= 9:
            channels.add(digits)
    for match in _EMAIL_CANDIDATE_RE.finditer(text or ""):
        channels.add(match.group(0).lower())
    return frozenset(channels)


def validate_contact_grounding(reply: str, evidence: str) -> frozenset[str]:
    """Contact channels the reply states that the turn's evidence never contained.

    ``evidence`` is the text the model was actually given: tool results plus the
    system prompt and the candidate's own message. A channel present there (a KB
    hotline, the API guide's support e-mail, the candidate's number) passes; any
    other number or address in the reply is an invention.
    """
    stated = extract_contact_channels(reply)
    if not stated:
        return frozenset()
    return frozenset(stated - extract_contact_channels(evidence))


# ── Active-project payload validation ────────────────────────────────────────
# ``list_active_projects`` answers are composed by the LLM agent from the payload
# (project rows + presentation contract); grounding only validates the
# composed prose against the surfaced evidence. There is deliberately NO
# deterministic reply replacement here anymore — the agent owns the final text.


def active_project_safe_reply(tool_result: object) -> str | None:
    """Validate one active-project tool payload and return its presentation contract."""
    first_line = str(tool_result).partition("\n")[0]
    if not first_line.startswith(_ACTIVE_PROJECT_LOOKUP_PREFIX):
        return None
    try:
        payload = json.loads(first_line.removeprefix(_ACTIVE_PROJECT_LOOKUP_PREFIX))
    except (TypeError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    status = payload["status"] if "status" in payload else None
    projects = payload["projects"] if "projects" in payload else None
    total = payload["total"] if "total" in payload else None
    safe_reply = payload["safe_reply"] if "safe_reply" in payload else None
    if status not in _ACTIVE_PROJECT_LOOKUP_STATUSES or not isinstance(projects, list):
        return None
    if not isinstance(total, int) or isinstance(total, bool):
        return None
    if status == "matched":
        # A matched payload may legitimately carry zero rows (a named company
        # matched nothing, or an unknown focused slug) — rows that exist must be
        # groundable project evidence.
        if any(
            not isinstance(project, dict)
            or not isinstance(project.get("id"), str)
            or not isinstance(project.get("project"), str)
            for project in projects
        ):
            return None
    elif projects:
        return None
    if not isinstance(safe_reply, str) or not safe_reply.strip():
        return None
    return safe_reply.strip()


def ground_reply(
    reply: str,
    tool_results: list[str],
    *,
    allowed_text: str = "",
    trace_sink=None,
) -> "str | _UngroundedContact":
    """Validate LLM prose against surfaced evidence without replacing it.

    Structured job payloads inform the model but never become a separately
    rendered final answer. This keeps every normal recruitment answer on the
    LLM route while retaining the job-ID hallucination guard.

    ``allowed_text`` is the prompt text the model worked from (system prompt +
    the candidate's message). Callers that pass it also arm the contact-channel
    guard: a phone number or e-mail the reply states without support in the tool
    results or that prompt text is an invention, and this function returns
    :class:`_UngroundedContact` naming the offending channels so the caller can
    ask the model to rewrite (never a code-authored replacement).
    """
    for tool_result in reversed(tool_results or []):
        first_line = str(tool_result).partition("\n")[0]
        if not first_line.startswith(_ACTIVE_PROJECT_LOOKUP_PREFIX):
            continue
        if active_project_safe_reply(tool_result) is None:
            logger.warning("active-project tool returned malformed grounding payload")

    try:
        from app.core.config import get_settings

        if not getattr(get_settings(), "grounding_check_enabled", True):
            if trace_sink is not None:
                trace_sink.record_decision("grounding_verdict", "skipped")
            return reply
        surfaced = extract_surfaced_ids(tool_results)
        surfaced_entities = extract_surfaced_entities(tool_results)
        result = validate_grounding(reply, surfaced, surfaced_entities)
        sanitized = False
        if not result.is_grounded:
            sanitized = True
            logger.warning(
                "grounding_hallucination_stripped: %s cited ids, %s unsupported entities",
                len(result.hallucinated_ids),
                len(result.unsupported_entities),
            )
            reply = result.sanitized_reply
        if allowed_text:
            evidence = "\n".join(str(r or "") for r in tool_results or []) + "\n" + allowed_text
            unverified = validate_contact_grounding(reply, evidence)
            if unverified:
                if trace_sink is not None:
                    trace_sink.record_decision("grounding_verdict", "sanitized")
                logger.warning(
                    "grounding_contact_unverified: %s channel(s)", len(unverified)
                )
                return _UngroundedContact(channels=tuple(sorted(unverified)))
        if trace_sink is not None:
            trace_sink.record_decision(
                "grounding_verdict", "sanitized" if sanitized else "grounded"
            )
        return reply
    except Exception:  # noqa: BLE001
        if trace_sink is not None:
            trace_sink.record_decision("grounding_verdict", "skipped")
        logger.debug("grounding check skipped (non-fatal)", exc_info=True)
        return reply
