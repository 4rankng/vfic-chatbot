"""Tests for find_reconcile_candidates — the loop-free recovery predicate.

Pure unit tests with mocked DB sessions. The critical assertions verify that
the SQL predicate is loop-safe: only ``WORKER``-newest or ``BOT/PENDING``-newest
conversations are returned; ``BOT/SENT``, ``BOT/SUPPRESSED``, and in-grace messages
are excluded.
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
        now=now, grace_seconds=120, max_age_seconds=86400, limit=50,
    )

    assert result == [conv]
    db.scalars.assert_called_once()


async def test_returns_empty_list_when_no_candidates():
    db = _mock_db([])
    repo = ConversationRepository(db)

    now = datetime.now(timezone.utc)
    result = await repo.find_reconcile_candidates(
        now=now, grace_seconds=120, max_age_seconds=86400, limit=50,
    )

    assert result == []


async def test_sql_contains_loop_free_predicate():
    """The SQL must check for WORKER or BOT/PENDING as the newest message.

    This is the core loop-safety guarantee: a completed turn (SENT or SUPPRESSED)
    leaves BOT/SENT or BOT/SUPPRESSED as newest → neither matches → excluded.
    """
    db = _mock_db([])
    repo = ConversationRepository(db)

    now = datetime.now(timezone.utc)
    await repo.find_reconcile_candidates(
        now=now, grace_seconds=120, max_age_seconds=86400, limit=50,
    )

    call_args = db.scalars.call_args
    sql_text = str(call_args[0][0])  # the text(...) clause

    # Loop-safety: must match WORKER or BOT+PENDING (NOT SENT or SUPPRESSED)
    assert "m.sender = 'WORKER'" in sql_text
    assert "m.sender = 'BOT'" in sql_text
    assert "m.delivery_status = 'PENDING'" in sql_text

    # Must NOT match SENT or SUPPRESSED
    assert "SENT" not in sql_text
    assert "SUPPRESSED" not in sql_text

    # Must filter by eligible modes
    assert "'BOT', 'SEMI_AUTO'" in sql_text

    # Must check lock is free
    assert "bot_locked_until IS NULL" in sql_text

    # Must respect OPEN status
    assert "'OPEN'" in sql_text

    # Must have time bounds (grace + max_age)
    assert "now_minus_grace" in sql_text
    assert "now_minus_max_age" in sql_text

    # Must have a LIMIT
    assert "LIMIT :limit" in sql_text


async def test_sql_params_include_time_bounds():
    """Verify the grace and max_age parameters are computed correctly."""
    db = _mock_db([])
    repo = ConversationRepository(db)

    now = datetime(2026, 6, 30, 12, 0, 0, tzinfo=timezone.utc)
    await repo.find_reconcile_candidates(
        now=now, grace_seconds=120, max_age_seconds=86400, limit=50,
    )

    call_args = db.scalars.call_args
    params = call_args[0][1]  # second positional arg = params dict

    assert params["now"] == now
    # grace: now - 120s
    assert params["now_minus_grace"] == datetime(2026, 6, 30, 11, 58, 0, tzinfo=timezone.utc)
    # max_age: now - 86400s = 24h ago
    assert params["now_minus_max_age"] == datetime(2026, 6, 29, 12, 0, 0, tzinfo=timezone.utc)
    assert params["limit"] == 50
