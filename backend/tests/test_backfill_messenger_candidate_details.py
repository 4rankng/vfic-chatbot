"""The detail backfill must not out-run its own DB connection pool."""

from __future__ import annotations

import pytest

from scripts.backfill_messenger_candidate_details import _bounded_concurrency


class _Settings:
    def __init__(self, pool_size: int, max_overflow: int) -> None:
        self.db_pool_size = pool_size
        self.db_max_overflow = max_overflow


def _patch_pool(monkeypatch, *, pool_size: int, max_overflow: int) -> None:
    monkeypatch.setattr(
        "app.core.config.get_settings",
        lambda: _Settings(pool_size, max_overflow),
    )


def test_concurrency_within_the_pool_is_used_as_requested(monkeypatch):
    _patch_pool(monkeypatch, pool_size=10, max_overflow=2)

    assert _bounded_concurrency(6) == 6


def test_concurrency_above_the_pool_is_clamped_to_leave_one_connection(monkeypatch):
    """The production worker runs 4+2; asking for 8 killed the run mid-backfill.

    Each in-flight conversation holds a session for its whole history, so the
    requested concurrency is a connection count, not just a parallel task count.
    """
    _patch_pool(monkeypatch, pool_size=4, max_overflow=2)

    assert _bounded_concurrency(8) == 5


def test_a_pool_too_small_to_share_still_processes_one_conversation(monkeypatch):
    _patch_pool(monkeypatch, pool_size=1, max_overflow=0)

    assert _bounded_concurrency(8) == 1


@pytest.mark.parametrize("requested", [0, -3])
def test_a_nonsensical_request_still_yields_one(monkeypatch, requested):
    """argparse rejects these; the clamp must not turn them into a zero-task run."""
    _patch_pool(monkeypatch, pool_size=10, max_overflow=2)

    assert _bounded_concurrency(requested) == 1
