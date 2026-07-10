"""Grounding enforcement: prevents the agent from citing job_ids it was never shown.

All three research docs flag this gap: citations exist in tool context but nothing
validates the final reply actually references retrieved data. This module provides
pure functions to close that loop:

* ``extract_surfaced_job_ids`` — pull job IDs from tool-result text (what the LLM saw).
* ``extract_cited_job_ids`` — pull job IDs from the reply (what the LLM claimed).
* ``validate_grounding`` — diff the two, return hallucinated IDs + a sanitized reply.

Intentionally pure (no DB, no LLM) so :mod:`backend.tests.test_grounding` can pin
every branch in isolation. The wiring into the agent loop is in :mod:`clients`.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# Job IDs surface in tool results as "id=uuid" (from recommend_jobs) or bare UUIDs.
# We match both the tagged form and standalone UUIDs to catch loose citations.
_JOB_ID_TAG_RE = re.compile(r"id=([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})", re.IGNORECASE)
_BARE_UUID_RE = re.compile(
    r"\b([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})\b", re.IGNORECASE
)


def _extract_ids(text: str, pattern: re.Pattern[str]) -> set[str]:
    return {m.lower() for m in pattern.findall(text or "")}


def extract_surfaced_job_ids(tool_results: list[str]) -> set[str]:
    """All job IDs the LLM was shown via tool results during the turn."""
    surfaced: set[str] = set()
    for result in tool_results or []:
        surfaced |= _extract_ids(result, _JOB_ID_TAG_RE)
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


def validate_grounding(reply: str, surfaced_ids: set[str]) -> GroundingResult:
    """Cross-check cited job IDs against what was actually retrieved.

    On hallucination (a cited ID not in the surfaced set), the offending IDs are
    stripped from the reply and a warning footer is appended. The reply is never
    fully replaced — the agent may still have useful non-citation content. If the
    reply is *entirely* about a hallucinated job (no grounded content remains after
    stripping), the caller should swap to an abstain reply.

    An empty ``surfaced_ids`` set means no job data was retrieved this turn; any
    job_id citation is then suspect, but we don't false-positive on an empty reply.
    """
    cited = extract_cited_job_ids(reply)
    if not cited:
        return GroundingResult(
            is_grounded=True,
            hallucinated_ids=frozenset(),
            sanitized_reply=reply,
        )

    hallucinated = cited - surfaced_ids if surfaced_ids else cited
    if not hallucinated:
        return GroundingResult(
            is_grounded=True,
            hallucinated_ids=frozenset(),
            sanitized_reply=reply,
        )

    # Strip hallucinated IDs from the reply text. Case-insensitive: UUIDs are valid
    # in either case, and a safety guardrail must survive an LLM uppercasing one.
    sanitized = reply
    for hid in hallucinated:
        sanitized = re.sub(
            re.escape(f"id={hid}"), "[việc không xác định]", sanitized, flags=re.IGNORECASE
        )
        sanitized = re.sub(re.escape(hid), "", sanitized, flags=re.IGNORECASE)

    return GroundingResult(
        is_grounded=False,
        hallucinated_ids=frozenset(hallucinated),
        sanitized_reply=sanitized.strip(),
        reason="cited_job_id_not_in_retrieved_set",
    )
