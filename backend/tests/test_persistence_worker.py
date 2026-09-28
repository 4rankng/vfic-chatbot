"""Persistence worker tests for the combined candidate extraction job."""

from __future__ import annotations

from contextlib import asynccontextmanager
from types import SimpleNamespace
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

    class _FakeEmbedder:
        batch = fake_embedder

    clients = SimpleNamespace(embedder=_FakeEmbedder(), extractor=fake_extractor)

    with (
        patch("app.workers._db.worker_session", fake_worker_session),
        patch(
            "app.graph.client_cache.build_cached_extraction",
            AsyncMock(return_value=clients),
        ) as build_clients,
        patch(
            "app.composition.recruitment.run_candidate_persistence",
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

    build_clients.assert_awaited_once_with(db)
    persist.assert_awaited_once_with(
        db,
        embed_batch=fake_embedder,
        extractor=fake_extractor,
        chat_id="zalo_1",
        user_text="tôi tên Mai",
        bot_output="Chào Mai",
        expected_conversation_version=7,
        contact_id=None,
        conversation_id=None,
    )


@pytest.mark.asyncio
async def test_repeated_persist_jobs_reuse_one_cached_client_bundle(monkeypatch):
    """The extractor and embedder are built once per process, not once per job.

    Every SENT reply used to construct a fresh langchain client (and its own httpx
    pool) plus a TLS handshake, on a queue that shares the same droplet as the
    chat worker that deliberately caches these.
    """
    from app.graph import client_cache

    built: list[str] = []

    class _FakeEmbedder:
        def __init__(self) -> None:
            self.batch = AsyncMock()

    class _FakeLLM:
        def __init__(self, role: str) -> None:
            self.root_async_client = SimpleNamespace(
                close=lambda: built.append(f"closed:{role}")
            )

    def _chat_for_role(role, **_kwargs):
        built.append(f"llm:{role}")
        return _FakeLLM(role)

    def _build_minimax_extractor():
        built.append("extractor")
        return AsyncMock()

    def _build_embedder(_settings=None, **_kwargs):
        built.append("embedder")
        embedder = _FakeEmbedder()
        embedder._client = SimpleNamespace(
            aio=SimpleNamespace(aclose=AsyncMock(side_effect=lambda: built.append("closed:embedder")))
        )
        return embedder

    async def _cache_version(_name):
        return "v1"

    monkeypatch.setattr(client_cache, "_chat_for_role", _chat_for_role)
    monkeypatch.setattr(client_cache, "build_embedder", _build_embedder)
    monkeypatch.setattr("app.core.cache.cache_version", _cache_version)
    monkeypatch.setattr(
        "app.services.integration_settings.IntegrationSettingsService",
        lambda _db, **_kwargs: SimpleNamespace(
            resolve_openrouter=AsyncMock(
                return_value=SimpleNamespace(api_key="sk-or-test")
            )
        ),
    )
    monkeypatch.setattr(
        "app.graph.factories.build_minimax_extractor", _build_minimax_extractor
    )
    monkeypatch.setattr(
        "app.composition.recruitment.run_candidate_persistence", AsyncMock()
    )
    db = AsyncMock()

    @asynccontextmanager
    async def fake_worker_session():
        yield db

    monkeypatch.setattr("app.workers._db.worker_session", fake_worker_session)
    client_cache.reset_client_cache()
    try:
        bundles = [
            await client_cache.build_cached_extraction(db) for _ in range(4)
        ]
        # One construction, four reads of the same bundle.
        assert built.count("extractor") == 1
        assert built.count("embedder") == 1
        assert built.count("llm:extractor") == 1
        assert all(bundle is bundles[0] for bundle in bundles)

        # Shutdown still closes the extraction bundle's pools.
        await client_cache.aclose_client_cache()
        assert "closed:extractor" in built
        assert "closed:embedder" in built
    finally:
        client_cache.reset_client_cache()


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
            "app.composition.recruitment.run_candidate_persistence",
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


@pytest.mark.asyncio
async def test_oa_profile_worker_waits_for_inline_lookup_before_retrying():
    from app.workers.persistence_worker import _enrich_oa_profile_async

    db = object()
    enrichment = AsyncMock(return_value=True)

    @asynccontextmanager
    async def fake_worker_session():
        yield db

    class _Integration:
        def __init__(self, received_db) -> None:
            assert received_db is db

        async def resolve_zalo(self, account_key=None):
            return type("_Config", (), {"oa_access_token": "test-token"})()

        async def refresh_oa_access_token(self, account_key=None):
            return "refreshed-token"

    class _ProfileService:
        def __init__(self, received_db, _sender) -> None:
            assert received_db is db

        enrich_oa_user = enrichment

    with (
        patch("app.workers._db.worker_session", fake_worker_session),
        patch(
            "app.services.integration_settings.IntegrationSettingsService",
            _Integration,
        ),
        patch("app.services.zalo_oa_service.ZaloOASender"),
        patch(
            "app.services.profile_enrichment.ProfileEnrichmentService",
            _ProfileService,
        ),
    ):
        await _enrich_oa_profile_async(
            {"zalo_id": "oa:user-1", "user_id": "user-1"}
        )

    enrichment.assert_awaited_once_with(
        "oa:user-1",
        user_id="user-1",
        wait_for_inflight=True,
    )
