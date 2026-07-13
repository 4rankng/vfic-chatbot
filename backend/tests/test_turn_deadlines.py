"""Tests for TurnDeadline (Tech-Lead Directive §4) and parallel retrieval.

Covers:
- TurnDeadline.remaining / expired / budget_for for each stage
- Unbounded behaviour when overall deadline is unset (tests / legacy)
- RetrievalRepository.match_documents parallelization (vector + lexical concurrent)
- Degraded fallback when vector arm fails / times out
- Degraded fallback when lexical arm fails
- Both-arms-failed returns empty list
- No-lexical-terms fast exit (vector-only, legacy path)
- last_match_degraded flag is set correctly per scenario
"""

from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.graph.deadlines import TurnDeadline


# ─── TurnDeadline primitive ──────────────────────────────────────────────────


def test_deadline_unbounded_when_overall_unset():
    """An unset overall (0.0) → inf remaining, never expired, None budget."""
    d = TurnDeadline(overall=0.0, retrieval_budget=1.2, rerank_budget=0.6)
    assert d.remaining("overall") == float("inf")
    assert d.remaining("retrieval") == float("inf")
    assert d.remaining("rerank") == float("inf")
    assert d.expired("overall") is False
    assert d.expired("retrieval") is False
    assert d.budget_for("retrieval") is None
    assert d.budget_for("rerank") is None


def test_deadline_expired_when_past_overall():
    """A past-deadline → 0 remaining, expired True, 0 budget."""
    d = TurnDeadline(overall=time.time() - 10, retrieval_budget=1.2, rerank_budget=0.6)
    assert d.remaining("overall") == 0.0
    assert d.remaining("retrieval") == 0.0
    assert d.expired("retrieval") is True
    assert d.budget_for("retrieval") == 0.0


def test_deadline_remaining_capped_by_per_stage_budget():
    """Stage remaining = min(stage_budget, overall_remaining)."""
    # Overall 5s in the future, retrieval budget 1.2s → retrieval remaining ≤ 1.2.
    d = TurnDeadline(overall=time.time() + 5, retrieval_budget=1.2, rerank_budget=0.6)
    assert d.remaining("retrieval") == pytest.approx(1.2, abs=0.05)
    assert d.remaining("rerank") == pytest.approx(0.6, abs=0.05)
    # Overall remaining is the full 5s (minus a hair).
    assert 4.9 < d.remaining("overall") <= 5.0
    assert d.expired("retrieval") is False


def test_deadline_remaining_capped_by_overall_when_budget_larger():
    """If the per-stage budget exceeds overall remaining, overall wins."""
    # Overall 0.5s in the future, retrieval budget 1.2s → retrieval remaining ≤ 0.5.
    d = TurnDeadline(overall=time.time() + 0.5, retrieval_budget=1.2, rerank_budget=0.6)
    assert d.remaining("retrieval") <= 0.5
    assert d.remaining("rerank") <= 0.5


def test_deadline_unknown_stage_falls_back_to_overall():
    d = TurnDeadline(overall=time.time() + 5, retrieval_budget=1.2, rerank_budget=0.6)
    # Unknown stage → overall remaining, not 0.
    assert 4.9 < d.remaining("unknown_stage") <= 5.0


def test_deadline_from_state_reads_deadline_at_epoch():
    """from_state constructs from BotRunState.deadline_at_epoch + settings budgets."""
    state = SimpleNamespace(deadline_at_epoch=time.time() + 3)
    settings = SimpleNamespace(turn_retrieval_budget_seconds=1.5, turn_rerank_budget_seconds=0.7)
    d = TurnDeadline.from_state(state, settings)
    assert d.overall == pytest.approx(time.time() + 3, abs=0.1)
    assert d.retrieval_budget == 1.5
    assert d.rerank_budget == 0.7


def test_deadline_from_state_handles_unset_epoch():
    """state.deadline_at_epoch=0 → unbounded primitive."""
    state = SimpleNamespace(deadline_at_epoch=0.0)
    settings = SimpleNamespace(turn_retrieval_budget_seconds=1.5, turn_rerank_budget_seconds=0.7)
    d = TurnDeadline.from_state(state, settings)
    assert d.overall == 0.0
    assert d.remaining("retrieval") == float("inf")


# ─── Parallel retrieval with degraded fallback ───────────────────────────────
#
# These tests exercise RetrievalRepository.match_documents by patching the two
# underlying arm methods (_match_document_vector_rows + _match_document_lexical_rows)
# with AsyncMocks so we can simulate success/failure/timeout per arm without a DB.


@pytest.fixture
def repo():
    """A RetrievalRepository with a stub session; arm methods patched per-test."""
    from app.services.retrieval.repository import RetrievalRepository

    return RetrievalRepository(db=AsyncMock())


def _row(id: str, similarity: float = 0.9, rank: int = 1):
    """A minimal retrieval-row stand-in with the attributes RRF + rerank read.

    ``reciprocal_rank_fuse`` consumes a list and indexes by position (rank);
    ``rerank_if_enabled`` reads ``.similarity`` (or ``_mapping['similarity']``).
    A SimpleNamespace with both satisfies both.
    """
    return SimpleNamespace(id=id, similarity=similarity, rank=rank)


async def test_match_documents_no_lexical_terms_returns_vector_only(repo):
    """No lexical terms (query_text=None or empty) → vector-only fast exit."""
    repo._match_document_vector_rows = AsyncMock(return_value=["v1", "v2"])
    # Should NOT call lexical arm.
    rows = await repo.match_documents("emb", 5, "{}", query_text=None)
    assert rows == ["v1", "v2"]
    assert repo.last_match_degraded is None


async def test_match_documents_both_arms_succeed_fuses(repo):
    """Both arms succeed → RRF fusion + rerank."""
    repo._match_document_vector_rows = AsyncMock(return_value=[_row("v1", 0.9), _row("v2", 0.8)])
    repo._match_document_lexical_rows = AsyncMock(return_value=[_row("l1", 0.85)])
    rows = await repo.match_documents("emb", 5, "{}", query_text="bus schedule")
    # Fused+reranked: 3 distinct rows survive RRF.
    assert len(rows) == 3
    assert repo.last_match_degraded is None


async def test_match_documents_vector_arm_fails_degrades_to_lexical(repo):
    """Vector arm raises → lexical-only fallback, last_match_degraded set."""
    repo._match_document_vector_rows = AsyncMock(side_effect=RuntimeError("pgvector down"))
    repo._match_document_lexical_rows = AsyncMock(return_value=["l1", "l2"])
    rows = await repo.match_documents("emb", 5, "{}", query_text="bus schedule")
    assert rows == ["l1", "l2"]  # lexical-only (rerank is identity when disabled)
    assert repo.last_match_degraded == "retrieval_vector_failed"


async def test_match_documents_lexical_arm_fails_uses_vector_only(repo):
    """Lexical arm raises → vector-only fallback, last_match_degraded set."""
    repo._match_document_vector_rows = AsyncMock(return_value=["v1", "v2"])
    repo._match_document_lexical_rows = AsyncMock(side_effect=RuntimeError("trigram down"))
    rows = await repo.match_documents("emb", 5, "{}", query_text="bus schedule")
    assert rows == ["v1", "v2"]
    assert repo.last_match_degraded == "retrieval_lexical_failed"


async def test_match_documents_both_arms_fail_returns_empty(repo):
    """Both arms fail → empty list, last_match_degraded = both_arms_failed."""
    repo._match_document_vector_rows = AsyncMock(side_effect=RuntimeError("vector down"))
    repo._match_document_lexical_rows = AsyncMock(side_effect=RuntimeError("lexical down"))
    rows = await repo.match_documents("emb", 5, "{}", query_text="bus schedule")
    assert rows == []
    assert repo.last_match_degraded == "retrieval_both_arms_failed"


async def test_match_documents_arms_run_concurrently(repo):
    """Vector + lexical arms execute concurrently (gather), not sequentially.

    Verifies the Tech-Lead Directive §4 "Parallelize independent I/O" requirement:
    total wall-clock = max(vector, lexical), not sum. We assert this by giving
    each arm a small sleep and checking the total elapsed time is well under
    the sum of both sleeps.
    """

    async def slow_vector(*a, **kw):
        await asyncio.sleep(0.1)
        return ["v1"]

    async def slow_lexical(*a, **kw):
        await asyncio.sleep(0.1)
        return ["l1"]

    repo._match_document_vector_rows = slow_vector
    repo._match_document_lexical_rows = slow_lexical

    t0 = time.monotonic()
    await repo.match_documents("emb", 5, "{}", query_text="bus schedule")
    elapsed = time.monotonic() - t0

    # If sequential: 0.1 + 0.1 = 0.2s. If concurrent: ~0.1s. Allow slack.
    assert elapsed < 0.18, f"arms appear sequential (elapsed={elapsed:.3f}s)"


async def test_match_documents_vector_timeout_degrades_to_lexical(repo):
    """Vector arm exceeds its budget → lexical-only, last_match_degraded set.

    Uses a TurnDeadline with a tiny retrieval budget so the vector arm (which
    sleeps longer than the budget) is cancelled by asyncio.wait_for.
    """

    async def slow_vector(*a, **kw):
        await asyncio.sleep(1.0)  # far exceeds the 0.05s budget
        return ["v_late"]

    repo._match_document_vector_rows = slow_vector
    repo._match_document_lexical_rows = AsyncMock(return_value=["l1"])
    deadline = TurnDeadline(overall=time.time() + 10, retrieval_budget=0.05, rerank_budget=0.6)

    rows = await repo.match_documents("emb", 5, "{}", query_text="bus schedule", deadline=deadline)
    assert rows == ["l1"]
    assert repo.last_match_degraded == "retrieval_vector_failed"


async def test_match_documents_resets_degraded_flag_per_call(repo):
    """last_match_degraded is reset at the start of every call."""
    # First call: vector fails → degraded flag set.
    repo._match_document_vector_rows = AsyncMock(side_effect=RuntimeError("first fails"))
    repo._match_document_lexical_rows = AsyncMock(return_value=["l1"])
    await repo.match_documents("emb", 5, "{}", query_text="bus schedule")
    assert repo.last_match_degraded == "retrieval_vector_failed"

    # Second call: both succeed → flag should be reset to None.
    repo._match_document_vector_rows = AsyncMock(return_value=["v1"])
    repo._match_document_lexical_rows = AsyncMock(return_value=["l1"])
    await repo.match_documents("emb", 5, "{}", query_text="bus schedule")
    assert repo.last_match_degraded is None


async def test_match_documents_no_deadline_runs_unbounded(repo):
    """deadline=None (default) → arms run without asyncio.wait_for wrapping.

    Verifies legacy callers (no deadline argument) get pre-existing behaviour:
    both arms run to completion, no time-boxing.
    """
    repo._match_document_vector_rows = AsyncMock(return_value=[_row("v1", 0.9)])
    repo._match_document_lexical_rows = AsyncMock(return_value=[_row("l1", 0.85)])
    rows = await repo.match_documents("emb", 5, "{}", query_text="bus schedule")
    assert len(rows) == 2  # both arms' rows survive fusion
    assert repo.last_match_degraded is None
