"""Tests for find_reconcile_candidates — the loop-free recovery predicate.

Pure unit tests with mocked DB sessions: they pin the query shape the sweep
issues and the time bounds it computes.  What the predicate *selects* is proven
behaviorally, against a real PostgreSQL, in
``tests/integration/test_reconcile_superseded_inbound.py`` — the loop-safety
invariants (only never-processed inbound, stuck PENDING/SENDING, or a delivery
failure as the newest message; a deliberate SUPPRESSED silence never re-answered)
are properties of the SQL, not of its text.
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

from app.services.conversation.repository import ConversationRepository


def _mock_db(scalars_result: list | None = None) -> AsyncMock:
    """Create a mock async DB session that returns scalars_result from .scalars().all()."""
    db = AsyncMock()
    mock_result = MagicMock()
    mock_result.all.return_value = scalars_result or []
    db.scalars = AsyncMock(return_value=mock_result)
    return db


async def test_returns_candidates_from_db():
    """find_reconcile_candidates returns whatever the SQL query yields."""
    conv = MagicMock()
    db = _mock_db([conv])
    repo = ConversationRepository(db)

    now = datetime.now(timezone.utc)
    result = await repo.find_reconcile_candidates(
        now=now,
        grace_seconds=120,
        max_age_seconds=86400,
        limit=50,
    )

    assert result == [conv]
    db.scalars.assert_called_once()


async def test_returns_empty_list_when_no_candidates():
    db = _mock_db([])
    repo = ConversationRepository(db)

    now = datetime.now(timezone.utc)
    result = await repo.find_reconcile_candidates(
        now=now,
        grace_seconds=120,
        max_age_seconds=86400,
        limit=50,
    )

    assert result == []


async def test_sql_params_include_time_bounds():
    """Verify the grace and max_age parameters are computed correctly."""
    db = _mock_db([])
    repo = ConversationRepository(db)

    now = datetime(2026, 6, 30, 12, 0, 0, tzinfo=timezone.utc)
    await repo.find_reconcile_candidates(
        now=now,
        grace_seconds=120,
        max_age_seconds=86400,
        limit=50,
    )

    call_args = db.scalars.call_args
    params = call_args[0][1]  # second positional arg = params dict

    assert params["now"] == now
    # grace: now - 120s
    assert params["now_minus_grace"] == datetime(2026, 6, 30, 11, 58, 0, tzinfo=timezone.utc)
    # max_age: now - 86400s = 24h ago
    assert params["now_minus_max_age"] == datetime(2026, 6, 29, 12, 0, 0, tzinfo=timezone.utc)
    assert params["limit"] == 50
    # stale_lock_seconds default (60) → now - 60s, used by the stale-lock clause
    assert params["stale_cutoff"] == datetime(2026, 6, 30, 11, 59, 0, tzinfo=timezone.utc)
