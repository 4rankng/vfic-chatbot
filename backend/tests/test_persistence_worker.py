"""Persistence worker tests for the combined candidate extraction job."""
from __future__ import annotations

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, patch

import pytest


@pytest.mark.asyncio
async def test_persist_candidate_job_uses_one_combined_service_call():
    from app.workers.persistence_worker import _persist_candidate_async

    db = AsyncMock()

    @asynccontextmanager
    async def fake_worker_session():
        yield db

    fake_embedder = AsyncMock()
    fake_extractor = AsyncMock()

    with (
        patch("app.workers._db.worker_session", fake_worker_session),
        patch("app.graph.clients.GeminiEmbedder") as embedder_cls,
        patch("app.workers.persistence_worker._build_extractor", return_value=fake_extractor),
        patch(
            "app.services.candidate_extraction.CandidateExtractionService.persist",
            new_callable=AsyncMock,
        ) as persist,
    ):
        embedder_cls.return_value.batch = fake_embedder
        await _persist_candidate_async(
            {
                "chat_id": "zalo_1",
                "user_text": "tôi tên Mai",
                "bot_output": "Chào Mai",
            }
        )

    persist.assert_awaited_once_with(
        db,
        fake_embedder,
        fake_extractor,
        "zalo_1",
        "tôi tên Mai",
        "Chào Mai",
    )
