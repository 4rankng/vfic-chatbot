"""Tests for the ingestion state machine (Tech-Lead Directive §8)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.models.provenance import DocumentStatus
from app.services.ingestion.state_machine import (
    ALLOWED_TRANSITIONS,
    IllegalTransition,
    TERMINAL_STATES,
    transition,
)


def _doc(status: DocumentStatus) -> MagicMock:
    d = MagicMock()
    d.status = status.value
    d.id = 1
    return d


class _FakeDB:
    async def commit(self):
        pass

    async def refresh(self, doc):
        pass


# ─── ALLOWED_TRANSITIONS table ───────────────────────────────────────────────


def test_all_directive_states_present():
    """The 11 forward states + 4 failure states from directive §8."""
    expected = {
        "RECEIVED", "STORED", "PARSED", "NORMALIZED", "CLASSIFIED", "EXTRACTED",
        "VALIDATED", "REVIEW_REQUIRED", "APPROVED", "PUBLISHED", "INDEXED",
        "FAILED_TRANSIENT", "FAILED_PERMANENT", "QUARANTINED", "SUPERSEDED",
    }
    actual = {s.value for s in DocumentStatus}
    assert actual == expected


def test_terminal_states_have_no_outgoing_transitions():
    """INDEXED, FAILED_PERMANENT, QUARANTINED are terminal."""
    for terminal in TERMINAL_STATES:
        assert ALLOWED_TRANSITIONS[terminal] == set()


def test_failed_transient_can_retry_from_received():
    """FAILED_TRANSIENT → RECEIVED (retry from the start)."""
    assert DocumentStatus.RECEIVED in ALLOWED_TRANSITIONS[DocumentStatus.FAILED_TRANSIENT]


def test_superseded_can_re_ingest():
    """SUPERSEDED → RECEIVED (re-ingest as a new version)."""
    assert DocumentStatus.RECEIVED in ALLOWED_TRANSITIONS[DocumentStatus.SUPERSEDED]


def test_every_failure_state_reachable_from_main_path():
    """Each main-path state can transition to a failure state."""
    for state in [
        DocumentStatus.RECEIVED,
        DocumentStatus.STORED,
        DocumentStatus.PARSED,
        DocumentStatus.NORMALIZED,
        DocumentStatus.CLASSIFIED,
        DocumentStatus.EXTRACTED,
    ]:
        assert DocumentStatus.FAILED_TRANSIENT in ALLOWED_TRANSITIONS[state]
        assert DocumentStatus.FAILED_PERMANENT in ALLOWED_TRANSITIONS[state]


# ─── transition() behavior ───────────────────────────────────────────────────


async def test_transition_legal_succeeds():
    doc = _doc(DocumentStatus.RECEIVED)
    await transition(_FakeDB(), doc, DocumentStatus.STORED)
    assert doc.status == "STORED"


async def test_transition_idempotent_to_same_state():
    """Transitioning to the current state is a no-op (no raise)."""
    doc = _doc(DocumentStatus.PARSED)
    await transition(_FakeDB(), doc, DocumentStatus.PARSED)
    assert doc.status == "PARSED"


async def test_transition_illegal_raises():
    """VALIDATED → STORED is not in the table."""
    doc = _doc(DocumentStatus.VALIDATED)
    with pytest.raises(IllegalTransition, match="VALIDATED → STORED"):
        await transition(_FakeDB(), doc, DocumentStatus.STORED)


async def test_transition_from_terminal_raises():
    """Cannot leave a terminal state (except via the retry paths)."""
    doc = _doc(DocumentStatus.INDEXED)
    with pytest.raises(IllegalTransition):
        await transition(_FakeDB(), doc, DocumentStatus.PUBLISHED)


async def test_transition_carries_reason_in_error():
    doc = _doc(DocumentStatus.PARSED)
    with pytest.raises(IllegalTransition, match="corrupt PDF"):
        await transition(
            _FakeDB(), doc, DocumentStatus.APPROVED, reason="corrupt PDF"
        )


async def test_transition_to_failure_state_from_main_path():
    """EXTRACTED → FAILED_PERMANENT is legal (extraction found bad data)."""
    doc = _doc(DocumentStatus.EXTRACTED)
    await transition(
        _FakeDB(), doc, DocumentStatus.FAILED_PERMANENT, reason="schema mismatch"
    )
    assert doc.status == "FAILED_PERMANENT"


async def test_transition_review_required_from_validated():
    """VALIDATED → REVIEW_REQUIRED (critical fields need human sign-off)."""
    doc = _doc(DocumentStatus.VALIDATED)
    await transition(_FakeDB(), doc, DocumentStatus.REVIEW_REQUIRED)
    assert doc.status == "REVIEW_REQUIRED"


async def test_full_happy_path_chain():
    """RECEIVED → STORED → ... → INDEXED end-to-end."""
    db = _FakeDB()
    doc = _doc(DocumentStatus.RECEIVED)
    chain = [
        DocumentStatus.STORED,
        DocumentStatus.PARSED,
        DocumentStatus.NORMALIZED,
        DocumentStatus.CLASSIFIED,
        DocumentStatus.EXTRACTED,
        DocumentStatus.VALIDATED,
        DocumentStatus.APPROVED,
        DocumentStatus.PUBLISHED,
        DocumentStatus.INDEXED,
    ]
    for next_state in chain:
        await transition(db, doc, next_state)
    assert doc.status == "INDEXED"
