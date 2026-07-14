"""Tests for the LLM client cache warm-start hook.

The hook (``warm_llm_client_cache``) builds the ChatOpenAI + embedder clients
once at worker boot so the first candidate turn hits ``_client_cache`` instead
of paying the ~5-7s cold-construction cost. These tests pin two contracts:

1. On success, ``_build_cached_clients`` runs exactly once inside a session.
2. On failure, the error propagates (the ``run_worker`` caller wraps it in a
   try/except that logs and continues — documented here so the contract is
   explicit at the call site).
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, patch

import pytest


def test_only_webhook_workers_warm_chatbot_dependencies():
    from app.workers.run_worker import _is_interactive_worker

    assert _is_interactive_worker(["webhook_high"])
    assert _is_interactive_worker(["webhook_high", "persistence_low"])
    assert not _is_interactive_worker(["persistence_low"])


@pytest.mark.asyncio
async def test_warm_llm_client_cache_builds_clients_once():
    """The warm-start opens one worker session and builds clients exactly once."""
    from app.workers.chatbot_worker import warm_llm_client_cache

    db = AsyncMock()

    @asynccontextmanager
    async def fake_worker_session():
        yield db

    build = AsyncMock()

    with (
        patch("app.workers._db.worker_session", fake_worker_session),
        patch("app.graph.factories._build_cached_clients", build),
    ):
        await warm_llm_client_cache()

    build.assert_awaited_once_with(db)


@pytest.mark.asyncio
async def test_warm_llm_client_cache_propagates_errors():
    """A build failure surfaces to the caller (run_worker logs + continues).

    The warm-start itself does NOT swallow errors — that is the caller's job
    (mirrors the preload_imports contract). Pinning the propagation here means
    a future refactor that adds a bare try/except inside the hook would be
    caught: it would silently leave the cache cold and the dashboard's
    preamble p95 tail would return with no log signal.
    """
    from app.workers.chatbot_worker import warm_llm_client_cache

    @asynccontextmanager
    async def fake_worker_session():
        yield AsyncMock()

    with (
        patch("app.workers._db.worker_session", fake_worker_session),
        patch(
            "app.graph.factories._build_cached_clients",
            AsyncMock(side_effect=RuntimeError("db not ready")),
        ),
    ):
        with pytest.raises(RuntimeError, match="db not ready"):
            await warm_llm_client_cache()
