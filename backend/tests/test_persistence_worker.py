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

    class _FakeIntegrationSettings:
        def __init__(self, _db) -> None:
            pass

        async def resolve_openrouter(self):
            return type("_Config", (), {"api_key": "sk-or-test"})()

    class _FakeEmbedder:
        batch = fake_embedder

    with (
        patch("app.workers._db.worker_session", fake_worker_session),
        patch("app.graph.clients.build_embedder", return_value=_FakeEmbedder()),
        patch(
            "app.services.integration_settings.IntegrationSettingsService",
            _FakeIntegrationSettings,
        ),
        patch("app.workers.persistence_worker._build_extractor", return_value=fake_extractor),
        patch(
            "app.services.candidate_extraction.CandidateExtractionService.persist",
            new_callable=AsyncMock,
        ) as persist,
    ):
        await _persist_candidate_async(
            {
                "chat_id": "zalo_1",
                "user_text": "tôi tên Mai",
                "bot_output": "Chào Mai",
                "conversation_version": 7,
            }
        )

    persist.assert_awaited_once_with(
        db,
        fake_embedder,
        fake_extractor,
        "zalo_1",
        "tôi tên Mai",
        "Chào Mai",
        expected_conversation_version=7,
    )


@pytest.mark.asyncio
async def test_stale_stamped_persist_job_never_resolves_an_extractor():
    from app.workers.persistence_worker import _persist_candidate_async

    db = AsyncMock()

    @asynccontextmanager
    async def fake_worker_session():
        yield db

    class _InactiveInstallation:
        def __init__(self, _db) -> None:
            pass

        async def resolve_active(self):
            return None

    with (
        patch("app.workers._db.worker_session", fake_worker_session),
        patch(
            "app.services.installation.service.InstallationService", _InactiveInstallation
        ),
        patch(
            "app.services.integration_settings.IntegrationSettingsService.resolve_openrouter",
            new_callable=AsyncMock,
        ) as resolve_openrouter,
        patch(
            "app.services.candidate_extraction.CandidateExtractionService.persist",
            new_callable=AsyncMock,
        ) as persist,
    ):
        await _persist_candidate_async(
            {
                "chat_id": "zalo_1",
                "runtime_revision_id": "00000000-0000-4000-8000-000000000001",
                "authority_generation": 1,
                "runtime_fingerprint": "a" * 64,
            }
        )

    resolve_openrouter.assert_not_awaited()
    persist.assert_not_awaited()
